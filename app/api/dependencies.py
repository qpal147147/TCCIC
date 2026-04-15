from fastapi import Header, HTTPException, status

from app.configs.global_settings import global_settings


async def verify_api_key(x_api_key: str = Header(..., description="API key for authentication")):
    """
    Dependency that validates the X-API-Key header against the configured API_KEY.
    Returns HTTP 401 if the header is missing or does not match.
    """
    if x_api_key != global_settings.AUTH_KEY.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key.",
        )
