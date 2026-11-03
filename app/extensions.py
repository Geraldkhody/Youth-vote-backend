from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate

# Created here (not inside the app factory) so other files can import them
# before the app exists, then call .init_app(app) once the app is created.
db = SQLAlchemy()
migrate = Migrate()
