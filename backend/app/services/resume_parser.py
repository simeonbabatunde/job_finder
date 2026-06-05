import io
from pypdf import PdfReader
from docx import Document

from app.observability import log_event

class ResumeService:
    @staticmethod
    def extract_text_from_pdf(file_content: bytes) -> str:
        try:
            reader = PdfReader(io.BytesIO(file_content))
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text.strip()
        except Exception as e:
            log_event("resume_parser.pdf_failed", level="warning", error=str(e))
            return ""

    @staticmethod
    def extract_text_from_docx(file_content: bytes) -> str:
        try:
            doc = Document(io.BytesIO(file_content))
            text = "\n".join([para.text for para in doc.paragraphs])
            return text.strip()
        except Exception as e:
            log_event("resume_parser.docx_failed", level="warning", error=str(e))
            return ""

    @staticmethod
    def parse_resume(file_content: bytes, filename: str) -> str:
        if filename.lower().endswith(".pdf"):
            return ResumeService.extract_text_from_pdf(file_content)
        elif filename.lower().endswith(".docx"):
            return ResumeService.extract_text_from_docx(file_content)
        elif filename.lower().endswith(".txt"):
            return file_content.decode("utf-8", errors="ignore")
        else:
            raise ValueError("Unsupported file format. Please upload a PDF, DOCX, or TXT file.")
