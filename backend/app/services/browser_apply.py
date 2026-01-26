import asyncio
import os
import tempfile
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Page
from app.models import Profile
from app.agent.llm_factory import get_llm
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser

class BrowserApplyService:
    @staticmethod
    async def apply_to_job(job_url: str, profile: Profile, resume_bytes: bytes, resume_filename: str, cover_letter: Optional[str] = None) -> Dict[str, Any]:
        """
        Main entry point for autonomous job application.
        """
        if not profile:
            return {"status": "failed", "message": "User profile is required for auto-apply."}

        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            try:
                print(f"Navigating to {job_url}...")
                await page.goto(job_url, wait_until="networkidle", timeout=60000)
                
                # Check for "Apply" button or form
                # For prototype, we'll try a generic form filler
                result = await BrowserApplyService._fill_form_with_ai(page, profile, resume_bytes, resume_filename, cover_letter)
                
                return result
            except Exception as e:
                print(f"Apply Error for {job_url}: {e}")
                return {"status": "failed", "message": str(e)}
            finally:
                await browser.close()

    @staticmethod
    async def _fill_form_with_ai(page: Page, profile: Profile, resume_bytes: bytes, resume_filename: str, cover_letter: Optional[str] = None) -> Dict[str, Any]:
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

        # 2. Ask LLM for Mapping
        llm = get_llm(model_type="gemini")
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
                    print(f"Uploaded resume: {resume_filename}")
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
                    print(f"Filled {field}")

            # Submit (disabled in prototype for safety unless specifically requested)
            # await page.click(mapping["submit_button"])
            
            return {"status": "success", "message": "Form filled successfully (Submit pending confirmation)"}
            
        except Exception as e:
            return {"status": "failed", "message": f"AI Mapping failed: {str(e)}"}
