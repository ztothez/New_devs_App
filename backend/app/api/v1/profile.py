from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile
from fastapi.responses import Response
from typing import Dict, Any, List
import logging
import uuid
from datetime import datetime
from PIL import Image
import io

from ...core.auth import authenticate_request
from ...models.auth import AuthenticatedUser
from ...models.profile import (
    UserProfile, UserProfileUpdate, UserPreferences, UserPreferencesUpdate,
    NotificationPreference, NotificationPreferenceUpdate, AvatarUploadResponse,
    ProfileResponse
)
from ...database import supabase
from ...services.profile_store import ProfileStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/profile", tags=["profile"])

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
MAX_FILE_SIZE = 5 * 1024 * 1024
AVATAR_SIZE = (300, 300)

# In-memory avatar storage for Challenge Mode: user_id -> JPEG bytes
_avatar_bytes: Dict[str, bytes] = {}


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def resize_image(image_data: bytes, size: tuple = AVATAR_SIZE) -> bytes:
    try:
        image = Image.open(io.BytesIO(image_data))

        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
            image = background

        image.thumbnail(size, Image.Resampling.LANCZOS)

        output = io.BytesIO()
        image.save(output, format='JPEG', quality=85, optimize=True)
        return output.getvalue()

    except Exception as e:
        logger.error(f"Error resizing image: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file"
        )


def _use_local_store() -> bool:
    return ProfileStore.is_challenge_mode()


def _get_profile_bundle(user: AuthenticatedUser) -> ProfileResponse:
    if _use_local_store():
        return ProfileResponse(
            profile=UserProfile(**ProfileStore.get_profile(user.id, user.email)),
            preferences=UserPreferences(**ProfileStore.get_preferences(user.id)),
            notification_preferences=[
                NotificationPreference(**pref)
                for pref in ProfileStore.get_notification_preferences(user.id)
            ],
            unread_count=0,
        )

    now_iso = datetime.utcnow().isoformat()
    default_profile = ProfileStore.default_profile(user.id, user.email)
    default_preferences = ProfileStore.default_preferences(user.id)

    profile = None
    preferences = None
    notification_preferences: List[NotificationPreference] = []
    unread_count = 0

    try:
        profile_response = supabase.table('user_profiles').select('*').eq('user_id', user.id).execute()
        if profile_response.data:
            profile = UserProfile(**profile_response.data[0])
        else:
            profile = UserProfile(**default_profile)
    except Exception as profile_error:
        logger.warning(f"Error accessing user_profiles table for user {user.id}: {profile_error}")
        profile = UserProfile(**default_profile)

    try:
        preferences_response = supabase.table('user_preferences').select('*').eq('user_id', user.id).execute()
        if preferences_response.data:
            preferences = UserPreferences(**preferences_response.data[0])
        else:
            preferences = UserPreferences(**default_preferences)
    except Exception as preferences_error:
        logger.warning(f"Error accessing user_preferences table for user {user.id}: {preferences_error}")
        preferences = UserPreferences(**default_preferences)

    try:
        notification_prefs_response = supabase.table('notification_preferences').select('*').eq('user_id', user.id).execute()
        if notification_prefs_response.data:
            notification_preferences = [
                NotificationPreference(**pref) for pref in notification_prefs_response.data
            ]
        else:
            notification_preferences = [
                NotificationPreference(**pref)
                for pref in ProfileStore.default_notification_preferences(user.id)
            ]
    except Exception as notif_error:
        logger.warning(f"Error accessing notification_preferences table for user {user.id}: {notif_error}")
        notification_preferences = [
            NotificationPreference(**pref)
            for pref in ProfileStore.default_notification_preferences(user.id)
        ]

    try:
        unread_response = supabase.rpc('get_unread_notification_count', {'user_uuid': user.id}).execute()
        data = unread_response.data
        if isinstance(data, list):
            unread_count = len(data) if data else 0
        else:
            unread_count = data if data is not None else 0
    except Exception as unread_error:
        logger.warning(f"Error getting unread notification count for user {user.id}: {unread_error}")
        unread_count = 0

    return ProfileResponse(
        profile=profile,
        preferences=preferences,
        notification_preferences=notification_preferences,
        unread_count=unread_count,
    )


@router.get("", response_model=ProfileResponse)
async def get_profile(user: AuthenticatedUser = Depends(authenticate_request)):
    try:
        logger.info(f"User {user.email} is fetching their profile.")
        return _get_profile_bundle(user)
    except Exception as e:
        logger.error(f"Error fetching profile for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while fetching profile."
        )


@router.put("", response_model=UserProfile)
async def update_profile(
    profile_update: UserProfileUpdate,
    user: AuthenticatedUser = Depends(authenticate_request)
):
    try:
        logger.info(f"User {user.email} is updating their profile.")

        update_data = {
            field: value
            for field, value in profile_update.dict(exclude_unset=True).items()
            if value is not None
        }

        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )

        if _use_local_store():
            updated = ProfileStore.update_profile(user.id, update_data, user.email)
            return UserProfile(**updated)

        response = supabase.table('user_profiles').update(update_data).eq('user_id', user.id).execute()
        if response.data:
            return UserProfile(**response.data[0])

        updated = ProfileStore.update_profile(user.id, update_data, user.email)
        logger.info(f"Saved profile update to local store for user {user.id}")
        return UserProfile(**updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating profile."
        )


@router.put("/preferences", response_model=UserPreferences)
async def update_preferences(
    preferences_update: UserPreferencesUpdate,
    user: AuthenticatedUser = Depends(authenticate_request)
):
    try:
        logger.info(f"User {user.email} is updating their preferences.")

        update_data = preferences_update.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )

        if _use_local_store():
            updated = ProfileStore.update_preferences(user.id, update_data)
            return UserPreferences(**updated)

        response = supabase.table('user_preferences').update(update_data).eq('user_id', user.id).execute()
        if response.data:
            return UserPreferences(**response.data[0])

        updated = ProfileStore.update_preferences(user.id, update_data)
        logger.info(f"Saved preferences update to local store for user {user.id}")
        return UserPreferences(**updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating preferences for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating preferences."
        )


@router.put("/notification-preferences/{category}", response_model=NotificationPreference)
async def update_notification_preference(
    category: str,
    preference_update: NotificationPreferenceUpdate,
    user: AuthenticatedUser = Depends(authenticate_request)
):
    try:
        logger.info(f"User {user.email} is updating notification preferences for category {category}.")

        update_data = preference_update.dict(exclude_unset=True)
        if not update_data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No valid fields to update"
            )

        if _use_local_store():
            updated = ProfileStore.update_notification_preference(user.id, category, update_data)
            return NotificationPreference(**updated)

        response = (
            supabase.table('notification_preferences')
            .update(update_data)
            .eq('user_id', user.id)
            .eq('category', category)
            .execute()
        )

        if response.data:
            return NotificationPreference(**response.data[0])

        create_data = {'user_id': user.id, 'category': category, **update_data}
        response = supabase.table('notification_preferences').insert(create_data).execute()
        if response.data:
            return NotificationPreference(**response.data[0])

        updated = ProfileStore.update_notification_preference(user.id, category, update_data)
        logger.info(f"Saved notification preference to local store for user {user.id}")
        return NotificationPreference(**updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating notification preferences for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while updating notification preferences."
        )


@router.get("/avatar/{user_id}")
async def get_avatar(user_id: str):
    avatar = _avatar_bytes.get(user_id)
    if not avatar:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
    return Response(content=avatar, media_type="image/jpeg")


@router.post("/avatar", response_model=AvatarUploadResponse)
async def upload_avatar(
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(authenticate_request)
):
    try:
        logger.info(f"User {user.email} is uploading an avatar.")

        if not file.filename:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file selected")

        if not allowed_file(file.filename):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File type not allowed. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
            )

        file_content = await file.read()
        if len(file_content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File too large. Maximum size: {MAX_FILE_SIZE // (1024 * 1024)}MB"
            )

        resized_image = resize_image(file_content)

        if _use_local_store():
            _avatar_bytes[user.id] = resized_image
            avatar_url = f"/api/v1/profile/avatar/{user.id}"
            ProfileStore.set_avatar_url(user.id, avatar_url, user.email)
            return AvatarUploadResponse(
                avatar_url=avatar_url,
                message="Avatar uploaded successfully"
            )

        unique_filename = f"{user.id}/avatar_{uuid.uuid4().hex}.jpg"

        try:
            existing_files = supabase.storage.from_('profile-pictures').list(user.id)
            if existing_files:
                for existing_file in existing_files:
                    if existing_file['name'].startswith('avatar_'):
                        supabase.storage.from_('profile-pictures').remove([f"{user.id}/{existing_file['name']}"])
        except Exception as delete_error:
            logger.warning(f"Could not delete existing avatar: {delete_error}")

        upload_response = supabase.storage.from_('profile-pictures').upload(
            unique_filename,
            resized_image,
            file_options={'content-type': 'image/jpeg'}
        )

        if getattr(upload_response, 'status_code', None) != 200:
            _avatar_bytes[user.id] = resized_image
            avatar_url = f"/api/v1/profile/avatar/{user.id}"
            ProfileStore.set_avatar_url(user.id, avatar_url, user.email)
            return AvatarUploadResponse(
                avatar_url=avatar_url,
                message="Avatar uploaded successfully"
            )

        public_url = supabase.storage.from_('profile-pictures').get_public_url(unique_filename)
        profile_update = supabase.table('user_profiles').update({
            'avatar_url': public_url
        }).eq('user_id', user.id).execute()

        if not profile_update.data:
            ProfileStore.set_avatar_url(user.id, public_url, user.email)

        return AvatarUploadResponse(
            avatar_url=public_url,
            message="Avatar uploaded successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading avatar for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while uploading avatar."
        )


@router.delete("/avatar")
async def delete_avatar(user: AuthenticatedUser = Depends(authenticate_request)):
    try:
        logger.info(f"User {user.email} is deleting their avatar.")

        if _use_local_store() or user.id in _avatar_bytes:
            _avatar_bytes.pop(user.id, None)
            ProfileStore.clear_avatar(user.id, user.email)
            return {"message": "Avatar deleted successfully"}

        profile_response = supabase.table('user_profiles').select('avatar_url').eq('user_id', user.id).execute()
        if not profile_response.data or not profile_response.data[0].get('avatar_url'):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No avatar found")

        try:
            existing_files = supabase.storage.from_('profile-pictures').list(user.id)
            if existing_files:
                files_to_delete = [
                    f"{user.id}/{file['name']}"
                    for file in existing_files
                    if file['name'].startswith('avatar_')
                ]
                if files_to_delete:
                    supabase.storage.from_('profile-pictures').remove(files_to_delete)
        except Exception as delete_error:
            logger.warning(f"Could not delete avatar files: {delete_error}")

        supabase.table('user_profiles').update({'avatar_url': None}).eq('user_id', user.id).execute()
        return {"message": "Avatar deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting avatar for user {user.id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred while deleting avatar."
        )
