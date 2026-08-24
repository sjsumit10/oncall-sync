"""Version 1 of the public API."""

from fastapi import APIRouter, Depends

from app.api.v1 import auth, chat, identities, oncall, orgs, rules
from app.core.deps import require_csrf

# CSRF is enforced router-wide; it no-ops on safe methods and on requests that
# carry no session, so signup and login are not special-cased. Provider webhooks
# are mounted separately in main.py: they are authenticated by request signature,
# which is strictly stronger, and they must not depend on a browser session.
router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_csrf)])

router.include_router(auth.router)
router.include_router(orgs.router)
router.include_router(oncall.router)
router.include_router(chat.router)
router.include_router(rules.router)
router.include_router(identities.router)
