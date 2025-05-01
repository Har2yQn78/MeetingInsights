from ninja_jwt.authentication import JWTAuth
from ninja_jwt.settings import api_settings
from ninja_jwt.exceptions import AuthenticationFailed, InvalidToken
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from asgiref.sync import sync_to_async
import logging
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken as SimpleJWTInvalidToken

logger = logging.getLogger(__name__)
UserModel = get_user_model()

class AsyncJWTAuth(JWTAuth):
    @sync_to_async
    def _get_user_from_db(self, user_id):
        try:
            user = UserModel.objects.get(**{api_settings.USER_ID_FIELD: user_id})
            return user
        except UserModel.DoesNotExist:
            logger.warning(f"User not found for {api_settings.USER_ID_FIELD}: {user_id}")
            return None
        except Exception as e:
            logger.error(f"Error fetching user {user_id}: {e}", exc_info=True)
            return None

    @sync_to_async
    def _check_user_is_active(self, user):
         return user.is_active

    async def authenticate(self, request, token):
        if token is None:
             return None

        try:
            unverified_token = AccessToken(token)

            try:
                user_id = unverified_token[api_settings.USER_ID_CLAIM]
            except KeyError:
                logger.error(f"Token missing required claim: {api_settings.USER_ID_CLAIM}")
                raise AuthenticationFailed(_("Token contained no recognizable user identification"), code="user_id_claim_missing")
            user = await self._get_user_from_db(user_id)

            if user is None:
                raise AuthenticationFailed(_("User matching this token was not found"), code="user_not_found")
            is_active = await self._check_user_is_active(user)
            if not is_active:
                 logger.warning(f"Authentication failed for user {user_id}: User is inactive.")
                 raise AuthenticationFailed(_("User is inactive"), code="user_inactive")

            logger.debug(f"Successfully authenticated user {user_id}")
            return user

        except SimpleJWTInvalidToken as e:
            logger.warning(f"Invalid token received: {e}")
            raise InvalidToken(str(e)) from e
        except TokenError as e:
             logger.warning(f"Token processing error: {e}")
             raise InvalidToken(str(e)) from e
        except AuthenticationFailed:
             raise
        except Exception as e:
             logger.error(f"Unexpected error during async JWT authentication: {e}", exc_info=True)
             raise AuthenticationFailed(_("Authentication failed due to an unexpected error."), code="authentication_error")