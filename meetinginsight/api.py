from ninja_jwt.controller import NinjaJWTDefaultController
from ninja_extra import NinjaExtraAPI
from meetings.api import router as meetings_router
from transcripts.api import router as transcripts_router
from analysis.api import router as analysis_router
from chatbot.api import router as chatbot_router

api = NinjaExtraAPI()

api.add_router("/meetings/",    meetings_router)
api.add_router("/transcripts/", transcripts_router)
api.add_router("/analysis/",    analysis_router)
api.add_router("/chatbot/", chatbot_router)

api.register_controllers(NinjaJWTDefaultController)

@api.get("/health", summary="Health Check", description="Simple endpoint to check if the API is running.")
def health(request):
    return {"status": "ok"}


