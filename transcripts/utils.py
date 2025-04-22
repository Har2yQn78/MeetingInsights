import io
import fitz
from docx import Document
import logging

logger = logging.getLogger(__name__)

SUPPORTED_CONTENT_TYPES = {
    'application/pdf': 'pdf',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'docx',
    'text/plain': 'txt',
}

def extract_text_from_pdf(file_stream):
    try:
        doc = fitz.open(stream=file_stream, filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except Exception as e:
        logger.error(f"Error extracting text from PDF: {e}", exc_info=True)
        raise ValueError(f"Could not process PDF file: {e}")

def extract_text_from_docx(file_stream):
    try:
        document = Document(file_stream)
        text = "\n".join([para.text for para in document.paragraphs])
        return text
    except Exception as e:
        logger.error(f"Error extracting text from DOCX: {e}", exc_info=True)
        raise ValueError(f"Could not process DOCX file: {e}")

def extract_text_from_txt(file_stream):
    try:
        content_bytes = file_stream.read()
        return content_bytes.decode('utf-8')
    except UnicodeDecodeError:
        try:
            return content_bytes.decode('latin-1')
        except Exception as e:
             logger.error(f"Error decoding text file: {e}", exc_info=True)
             raise ValueError("Could not decode text file. Ensure it's UTF-8 or Latin-1 encoded.")
    except Exception as e:
        logger.error(f"Error reading text file: {e}", exc_info=True)
        raise ValueError(f"Could not read text file: {e}")

def extract_text(file: 'UploadedFile'):
    content_type = file.content_type
    file_stream = file.file
    if content_type == 'application/pdf':
        return extract_text_from_pdf(file_stream)
    elif content_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
        return extract_text_from_docx(file_stream)
    elif content_type == 'text/plain':
        return extract_text_from_txt(file_stream)
    else:
        supported_types = ", ".join(SUPPORTED_CONTENT_TYPES.keys())
        raise ValueError(f"Unsupported file type: {content_type}. Supported types are: {supported_types}")