# Meeting Analysis API & Application

This project provides a Django Ninja backend API and a Streamlit frontend application for managing meeting records, submitting transcripts, processing them using a simulated LLM analysis, and retrieving the results.

## Features

*   **Meeting Management:** CRUD operations for meetings (title, date, participants, JSON metadata).
*   **Transcript Management:** Submit transcripts as raw text or file uploads (.txt, .pdf, .md) associated with meetings.
*   **AI Analysis Workflow:**
    *   Asynchronous analysis of transcripts using Celery.
    *   Generates summary and extracts key points/action items (via LLM interaction).
    *   Provides status tracking (Pending, Processing, Completed, Failed).
    *   Includes basic error handling and retries for the analysis task.
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
│ ├── models.py 
│ ├── schemas.py 
│ ├── service.py 
│ ├── task.py 
│ └── views.py 
├── meetinginsight/
│ ├── init.py
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
├── .env.example
├── .gitignore
├── manage.py
├── requirements.txt
├── app.py 
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

5.  **Apply Database Migrations:**
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
*   **Client-Side Text Extraction (Streamlit):** The Streamlit app now performs text extraction from uploaded files (PDF, TXT, MD) *before* sending data to the `/analysis/process/direct/` endpoint. This simplifies the backend logic for that specific endpoint (it only needs to expect `raw_text`) but puts the extraction load on the Streamlit server process. It also requires installing extraction libraries (`PyMuPDF`) in the Streamlit environment. The backend `transcripts.utils` still exists but isn't used by this primary Streamlit workflow path.
*   **JWT Authentication:** `django-ninja-jwt` provides a simple and standard way to secure the API endpoints. Token refresh logic is handled in the Streamlit app.

## Testing

*   **Manual API Testing:** Use the interactive API documentation (`/api/docs`) to test individual endpoints. Tools like Postman or Insomnia can also be used.
*   **Frontend Testing:** Use the Streamlit application (`app.py`) to test the end-to-end workflows (login, submission, status polling, history view, deletion).


## Potential Future Enhancements

*   Add pagination and filtering to `analysis` and `transcript` list endpoints.
*   Add support for more file types (e.g., DOCX, audio/video with transcription service integration).
*   Implement more sophisticated monitoring for Celery tasks.
*   Refine the LLM prompts for better analysis results.