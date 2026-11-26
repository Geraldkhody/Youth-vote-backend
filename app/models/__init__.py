# Import models here so Flask-Migrate can see them when generating migrations.
from app.models.category import Category  # noqa: F401
from app.models.nominee import Nominee  # noqa: F401
from app.models.nomination import Nomination  # noqa: F401
from app.models.admin_user import AdminUser  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
from app.models.hubtel_log import HubtelLog  # noqa: F401
from app.models.voting_settings import VotingSettings  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401
from app.models.vote import Vote  # noqa: F401
from app.models.ussd_session import UssdSession  # noqa: F401
