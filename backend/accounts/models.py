import mongoengine as me
from datetime import datetime
from django.contrib.auth.hashers import make_password, check_password

class User(me.Document):
    email = me.StringField(required=True, unique=True)
    password = me.StringField(required=True)  # Argon2 hashed password
    storage_quota_bytes = me.IntField(default=5 * 1024 * 1024 * 1024)  # 5 GB default
    storage_used_bytes = me.IntField(default=0)
    created_at = me.DateTimeField(default=datetime.utcnow)

    meta = {
        'collection': 'users',
        'indexes': ['email']
    }

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False

    @property
    def pk(self):
        return str(self.id)

    def set_password(self, raw_password):
        # Uses PASSWORD_HASHERS setting (Argon2 by default)
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def to_dict(self):
        return {
            "id": str(self.id),
            "email": self.email,
            "storage_quota_bytes": self.storage_quota_bytes,
            "storage_used_bytes": self.storage_used_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
