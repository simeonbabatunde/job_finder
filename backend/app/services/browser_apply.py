import asyncio
import os
import tempfile
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Page
from app.models import Profile
from app.agent.llm_factory import get_llm
from app.observability import log_event, url_host
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

class BrowserApplyService:
    @staticmethod
    def true_submit_enabled() -> bool:
        return os.getenv("ENABLE_TRUE_AUTO_SUBMIT", "false").strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    async def apply_to_job(job_url: str, profile: Profile, resume_bytes: bytes, resume_filename: str, cover_letter: Optional[str] = None, submit: bool = False) -> Dict[str, Any]:
        """
        Main entry point for autonomous job application.
        """
        log_event(
            "browser_apply.started",
            source_host=url_host(job_url),
            submit_requested=submit,
            has_resume=bool(resume_bytes),
            has_cover_letter=bool(cover_letter),
        )
        if not profile:
            log_event("browser_apply.blocked", level="warning", source_host=url_host(job_url), reason="missing_profile")
            return {"status": "failed", "message": "User profile is required for auto-apply."}
        if submit and not BrowserApplyService.true_submit_enabled():
            log_event(
                "browser_apply.blocked",
                level="warning",
                source_host=url_host(job_url),
                reason="true_submit_disabled",
            )
            return {
                "status": "blocked",
                "message": "Automated final submit is disabled. Set ENABLE_TRUE_AUTO_SUBMIT=true only for an approved pilot.",
            }

        async with async_playwright() as p:
            # Launch browser with sandbox args for Docker
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                log_event("browser_apply.navigating", source_host=url_host(job_url))
                await page.goto(job_url, wait_until="networkidle", timeout=60000)
                
                # Check for "Apply" button or form
                # For prototype, we'll try a generic form filler
                result = await BrowserApplyService._fill_form_with_ai(page, profile, resume_bytes, resume_filename, cover_letter, submit=submit)
                log_event(
                    "browser_apply.completed",
                    source_host=url_host(job_url),
                    status=result.get("status"),
                    submit_requested=submit,
                )
                return result
            except Exception as e:
                log_event(
                    "browser_apply.failed",
                    level="error",
                    source_host=url_host(job_url),
                    error=str(e),
                )
                return {"status": "failed", "message": str(e)}
            finally:
                await browser.close()

    @staticmethod
    async def _fill_form_with_ai(page: Page, profile: Profile, resume_bytes: bytes, resume_filename: str, cover_letter: Optional[str] = None, submit: bool = False) -> Dict[str, Any]:
        """
        Uses LLM to identify fields and fill the form.
        """
        # 1. Capture Page State (Simplified DOM)
        dom_snapshot = await page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll('input, select, textarea, button'));
            return inputs.map(i => ({
                tag: i.tagName,
                type: i.type,
                name: i.name,
                id: i.id,
                placeholder: i.placeholder,
                text: i.innerText || i.value,
                label: document.querySelector(`label[for="${i.id}"]`)?.innerText || ''
            })).filter(i => i.type !== 'hidden').slice(0, 50); // Limit to top 50 elements
        }""")
        log_event("browser_apply.dom_snapshot", visible_controls_count=len(dom_snapshot))

        # 2. Ask LLM for Mapping
        llm = get_llm(model_type="openai")
        parser = JsonOutputParser()
        
        prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an autonomous browser agent. Given a list of HTML elements on a job application page, identify the CSS selectors or IDs to fill based on the user's profile. Return a JSON object mapping 'field_name' to 'selector'. Also identify 'submit_button' and 'resume_upload'."),
            ("user", "Elements: {elements}\n\nProfile: {profile}\n\nIdentify selectors in JSON format:")
        ])
        
        chain = prompt | llm | parser
        
        try:
            mapping = await chain.ainvoke({
                "elements": dom_snapshot,
                "profile": profile.model_dump()
            })
            
            # 3. Perform Actions
            # Upload Resume first if found
            if "resume_upload" in mapping:
                with tempfile.NamedTemporaryFile(suffix=os.path.splitext(resume_filename)[1], delete=False) as tmp:
                    tmp.write(resume_bytes)
                    tmp_path = tmp.name
                
                try:
                    await page.set_input_files(mapping["resume_upload"], tmp_path)
                    log_event("browser_apply.resume_uploaded")
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

            # Fill Text Fields
            fields_to_fill = {
                "first_name": profile.first_name,
                "last_name": profile.last_name,
                "email": profile.email,
                "phone": profile.phone,
                "linkedin": profile.linkedin_url,
                "portfolio": profile.portfolio_url,
                "cover_letter": cover_letter
            }

            for field, value in fields_to_fill.items():
                if field in mapping and value:
                    await page.fill(mapping[field], value)
                    log_event("browser_apply.field_filled", field_name=field)

            # Submit only when the outer service has passed the explicit pilot gate.
            if submit and "submit_button" in mapping:
                log_event("browser_apply.submit_clicked")
                await page.click(mapping["submit_button"])
                # Wait for navigation or success message? 
                # For now just wait a bit
                await page.wait_for_timeout(3000)
                return {"status": "success", "message": "Application submitted successfully!"}
            
            return {"status": "success", "message": "Form filled successfully (Submit pending confirmation)" if not submit else "Form filled but submit button not found/clicked"}
            
        except Exception as e:
            log_event("browser_apply.mapping_failed", level="error", error=str(e))
            return {"status": "failed", "message": f"AI Mapping failed: {str(e)}"}
