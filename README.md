# Meeting Analysis API & Application With RAG Q&A

This project provides a Django Ninja backend API and a Streamlit frontend application for managing meeting records, submitting transcripts, processing them for analysis (summary, key points), generating vector embeddings, and enabling Retrieval-Augmented Generation (RAG) based Question & Answering on the transcript content.
## Features

*   **Meeting Management:** CRUD operations for meetings (title, date, participants, JSON metadata).
*   **Transcript Management:** Submit transcripts as raw text or file uploads (.txt, .pdf, .md) associated with meetings.
*   **AI Analysis Workflow:**
    *   Asynchronous analysis of transcripts using Celery.
    *   Generates summary and extracts key points/action items (via LLM interaction).
    *   Provides status tracking (Pending, Processing, Completed, Failed).
    *   Includes basic error handling and retries for the analysis task.
*   **AI RAG Workflow (Q&A):**
    * Asynchronous generation of text embeddings for completed transcripts using Celery and Mistral AI embedding models.
    * Stores text chunks and embeddings in PostgreSQL using the pgvector extension.
    * Provides status tracking for embedding generation (None, Pending, Processing, Completed, Failed).
    * Allows users to ask natural language questions about a specific transcript via the API.
    * Retrieves relevant text chunks from the vector store based on the question.
    * Generates answers using an LLM (Mistral AI) based on the retrieved context and the user's question.
*   **Data Retrieval:** Fetch meeting details, transcript status/content, and analysis results.
*   **API:** Modern API built with Django Ninja (FastAPI-like experience in Django).
*   **Authentication:** JWT-based authentication securing API endpoints.
*   **Frontend:** Interactive Streamlit application for:
    *   Login/Logout.
    *   Submitting new transcripts (text paste or file upload with client-side text extraction).
    *   Viewing analysis status updates in real-time (polling).
    *   Browsing historical meeting analysis results.
    *   Deleting meetings.
    *   Viewing original transcript text alongside analysis results.
*   **Logging:** Implemented throughout the backend, especially for the analysis task.

## Project Structure
```angular2html

├── analysis/ 
│ ├── migrations/
│ ├── init.py
│ ├── admin.py
│ ├── api.py 
│ ├── apps.py
│ ├── auth.py
│ ├── models.py 
│ ├── schemas.py 
│ ├── service.py 
│ ├── task.py 
│ └── views.py 
├── chatbot/          
│   ├── migrations/
│   ├── __init__.py
│   ├── admin.py
│   ├── api.py         
│   ├── apps.py
│   ├── auth.py   
│   ├── models.py     
│   ├── schemas.py    
│   ├── services.py   
│   └── tasks.py     
├── meetinginsight/
│ ├── init.py
│ ├── api.py
│ ├── asgi.py
│ ├── celery.py 
│ ├── settings.py
│ ├── urls.py 
│ └── wsgi.py
├── meetings/
│ ├── migrations/
│ ├── init.py
│ ├── admin.py
│ ├── api.py 
│ ├── apps.py
│ ├── models.py 
│ ├── schemas.py 
│ ├── tests.py 
│ └── views.py
├── transcripts/ 
│ ├── migrations/
│ ├── init.py
│ ├── admin.py
│ ├── api.py 
│ ├── apps.py
│ ├── models.py 
│ ├── schemas.py 
│ ├── tests.py
│ ├── utils.py 
│ └── views.py
├── app.py 
├── docker-compose.yaml 
├── Dockerfile
├── .env.copy
├── .gitignore
├── manage.py
├── requirements.txt
└── README.md 
```

## Setup and Running Locally

**Prerequisites:**

*   Python 3.8+
*   PostgreSQL Database (running locally or accessible)
*   Redis (or another Celery broker, Redis recommended)
*   `pip` package installer

**Backend Setup:**

1.  **Clone the repository:**
    ```bash
    git clone <https://github.com/Har2yQn78/MeetingInsights.git>
    cd <MeetingInsights>
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv venv
    # On Windows:
    # venv\Scripts\activate
    # On macOS/Linux:
    # source venv/bin/activate
    ```

3.  **Install backend dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure Environment Variables:**
    *   Copy `.env.example` to `.env`.
    *   Edit `.env` and fill in your specific configurations:
        *   `SECRET_KEY`: A strong, unique secret key for Django.
        *   `DEBUG`: Set to `True` for development, `False` for production.
        *   `DATABASE_URL`: Your PostgreSQL connection string (e.g., `postgres://user:password@host:port/dbname`).
        *   `CELERY_BROKER_URL`: Your Redis connection string (e.g., `redis://localhost:6379/0`).
        *   `CELERY_RESULT_BACKEND`: Often same as broker for simplicity (e.g., `redis://localhost:6379/0`).
        *   `OPENROUTER_API_KEY`: Your API key for OpenRouter AI (required for analysis).
        *   *(Optional)* Add other settings as needed (CORS origins, etc.).
        *   `MISTRAL_API_KEY`: Your API key for MISTRALAI
        *   `MISTRAL_EMBEDDING_DIM`: 1024
        *   `MISTRAL_EMBED_MODEL`:
        *   `MISTRAL_CHAT_MODEL`:

5.  **Apply Database Migrations:**
    ```bash
    python manage.py makemigrations
    ```
    
    ```bash
    python manage.py migrate
    ```

6.  **Create a Superuser (for Django Admin):**
    ```bash
    python manage.py createsuperuser
    ```

7.  **Run the Django Development Server:**
    ```bash
    python manage.py runserver
    # API will be available at http://127.0.0.1:8000/api/docs
    ```

8.  **Run the Celery Worker:**
    Open *another terminal*, activate the virtual environment (`source venv/bin/activate` or `venv\Scripts\activate`), and run:
    ```bash
    celery -A meetinginsight worker --loglevel=info
    ```
    *(If using Windows, you might need `celery -A backend worker --pool=solo --loglevel=info` or install `gevent`: `pip install gevent` then run the original command).*

**Frontend (Streamlit) Setup:**

1.  **Ensure you are in the project root directory.**
2.  **Install Streamlit and necessary libraries (if not already included in `requirements.txt` used by backend):**
    ```bash
    # Ensure PyMuPDF is installed for PDF extraction
    pip install streamlit requests PyMuPDF
    ```
3.  **Run the Streamlit App:**
    ```bash
    streamlit run app.py
    ```
    The Streamlit app will typically open automatically in your browser (e.g., at `http://localhost:8501`).

**Accessing the Application:**

*   **API Documentation:** `http://127.0.0.1:8000/api/docs` (Swagger UI) or `/api/redoc`
*   **Django Admin:** `http://127.0.0.1:8000/admin/` (Login with superuser credentials)
*   **Streamlit Frontend:** `http://localhost:8501` (or the URL provided when starting Streamlit)

## Architectural Decisions & Trade-offs

*   **Django Ninja:** Chosen for its modern, FastAPI-like syntax, automatic interactive documentation, and type hinting, while leveraging the robust Django ecosystem (ORM, Admin).
*   **Celery:** Used for asynchronous task processing, essential for offloading potentially long-running AI analysis tasks from the web request cycle, improving API responsiveness. Redis is the recommended broker for ease of setup and performance.
*   **PostgreSQL:** A powerful relational database suitable for structured data like meetings and transcript metadata.
*   **JSON Fields:** Used for `participants` and `metadata` in `Meeting`, and `key_points` in `AnalysisResult` to allow flexibility without overly complex schemas for potentially variable data structures. Trade-off is slightly less performant querying within the JSON compared to normalized fields.
*   **AsyncOpenAI / OpenRouter:** The `TranscriptAnalysisService` uses `async` operations for interacting with the LLM API, making the Celery task more efficient by not blocking on I/O. OpenRouter provides flexibility in choosing models.
*   **RAG Implementation:** Uses `LlamaIndex` as the orchestration layer for RAG. Text is chunked (SentenceSplitter) before embedding. Embeddings are generated asynchronously via a Celery task (chatbot.tasks.generate_embeddings_task) triggered after successful initial analysis. llama-index-vector-stores-postgres integrates LlamaIndex with the pgvector database. The Q&A API endpoint retrieves relevant chunks based on question similarity and uses Mistral's chat model for answer generation based on context.
*   **Client-Side Text Extraction (Streamlit):** The Streamlit app now performs text extraction from uploaded files (PDF, TXT, MD) *before* sending data to the `/analysis/process/direct/` endpoint. This simplifies the backend logic for that specific endpoint (it only needs to expect `raw_text`) but puts the extraction load on the Streamlit server process. It also requires installing extraction libraries (`PyMuPDF`) in the Streamlit environment. The backend `transcripts.utils` still exists but isn't used by this primary Streamlit workflow path.
*   **JWT Authentication:** `django-ninja-jwt` provides a simple and standard way to secure the API endpoints. Token refresh logic is handled in the Streamlit app.


## Testing

This project includes automated tests for the backend API components and utilities. Manual testing via the API docs and the Streamlit UI is also recommended.

**1. Automated Backend Tests:**

*   The backend uses Django's built-in test framework (`django.test.TestCase`). Tests cover API endpoints (CRUD operations, authentication, error handling) and internal logic (like the analysis task processing).
*   External dependencies like the LLM service and Celery task execution are mocked during testing to ensure tests are fast and isolated.
*   **Running Tests:**
    *   Ensure you have activated your virtual environment and installed all dependencies (`pip install -r requirements.txt`).
    *   Navigate to the project root directory (containing `manage.py`).
    *   Run all tests for the entire project:
        ```bash
        python manage.py test
        ```
    *   Run tests for a specific application (e.g., `meetings`, `transcripts`, `analysis`):
        ```bash
        python manage.py test analysis
        ```
    *   You should see output indicating the number of tests run and whether they passed (`OK`) or failed.

**2. Manual API Testing:**

*   Use the interactive API documentation available when the Django server is running:
    *   **Swagger UI:** `http://127.0.0.1:8000/api/docs`
    *   **ReDoc:** `http://127.0.0.1:8000/api/redoc`
*   These interfaces allow you to authorize (using a JWT token obtained from login) and send requests to individual API endpoints directly from your browser.
*   External tools like Postman or Insomnia can also be configured to interact with the API.

**3. Frontend & End-to-End Testing:**

*   Run the Streamlit application (`streamlit run app.py`).
*   Use the web interface to test the complete user workflows:
    *   Login and Logout.
    *   Creating meetings (if exposed in UI).
    *   Submitting new transcripts (via text paste and file upload).
    *   Observing status updates for processing transcripts.
    *   Viewing completed analysis results.
    *   Navigating history.
    *   Deleting meetings/transcripts (if applicable).

*   **Manual API Testing:** Use the interactive API documentation (`/api/docs`) to test individual endpoints. Tools like Postman or Insomnia can also be used.
*   **Frontend Testing:** Use the Streamlit application (`app.py`) to test the end-to-end workflows (login, submission, status polling, history view, deletion).


## Potential Future Enhancements

*   Add pagination and filtering to `analysis` and `transcript` list endpoints.
*   Add support for more file types (e.g., DOCX, audio/video with transcription service integration).
*   Implement more sophisticated monitoring for Celery tasks.
*   Refine the LLM prompts for better analysis results.