"""User API endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from core.database import get_db
from core.auth import get_current_user, AuthContext
from core.services.billing_service import BillingService
from models.user import User
from schemas.user_schemas import SyncUserResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/sync",
    response_model=SyncUserResponse,
    summary="Sync user from Clerk",
    description="Creates or returns the user record based on the authenticated Clerk user. Idempotent.",
    operation_id="sync_user",
    responses={
        401: {"description": "Missing or invalid Clerk JWT token"},
        500: {"description": "Database error"},
    },
)
async def sync_user(auth: AuthContext = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    user_id = auth.user_id

    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalars().first()

    if not user:
        new_user = User(id=user_id)
        db.add(new_user)
        try:
            await db.commit()
            status = "created"
        except IntegrityError:
            await db.rollback()
            logger.debug("User sync race condition handled: %s", user_id)
            status = "exists"
        except Exception as e:
            logger.error("Database error on user sync for %s: %s", user_id, e)
            await db.rollback()
            raise HTTPException(status_code=500, detail="Database operation failed")
    else:
        status = "exists"

    # Ensure billing account exists (idempotent — covers users created before billing)
    try:
        billing = BillingService(db)
        await billing.create_customer_for_user(
            clerk_user_id=user_id,
            email="",
        )
    except Exception as e:
        logger.warning("Failed to ensure billing account for user %s: %s", user_id, e)

    return {"status": status, "user_id": user_id}
