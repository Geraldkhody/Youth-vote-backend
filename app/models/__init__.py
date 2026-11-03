# Import models here so Flask-Migrate can see them when generating migrations.
from app.models.category import Category  # noqa: F401
from app.models.nominee import Nominee  # noqa: F401
from app.models.nomination import Nomination  # noqa: F401
from app.models.admin_user import AdminUser  # noqa: F401
from app.models.audit_log import AuditLog  # noqa: F401
