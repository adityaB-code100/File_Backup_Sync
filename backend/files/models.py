import mongoengine as me
from datetime import datetime
from accounts.models import User

class Folder(me.Document):
    name = me.StringField(required=True)
    owner = me.ReferenceField(User, required=True)
    parent_folder = me.ReferenceField('self', null=True, default=None)
    created_at = me.DateTimeField(default=datetime.utcnow)
    deleted = me.BooleanField(default=False)

    meta = {
        'collection': 'folders',
        'indexes': ['owner', 'parent_folder', 'deleted']
    }

    def to_dict(self):
        return {
            "id": str(self.id),
            "name": self.name,
            "owner": str(self.owner.id) if self.owner else None,
            "parent_id": str(self.parent_folder.id) if self.parent_folder else None,
            "type": "folder",
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "deleted": self.deleted
        }

class FileVersion(me.Document):
    file = me.ReferenceField('File', required=True)
    version_number = me.IntField(required=True)
    content_hash = me.StringField(required=True)  # SHA-256 hex string of pre-encryption plaintext
    size_bytes = me.IntField(required=True)
    storage_path = me.StringField(required=True)
    wrapped_dek = me.StringField(required=True)   # Base64 string of encrypted DEK
    dek_iv = me.StringField(required=True)        # Base64 string of IV used to wrap DEK
    iv = me.StringField(required=True)            # Base64 string of IV used for file content encryption
    created_at = me.DateTimeField(default=datetime.utcnow)
    uploaded_by = me.ReferenceField(User, required=True)

    meta = {
        'collection': 'file_versions',
        'indexes': ['file', 'version_number', 'content_hash']
    }

    def to_dict(self):
        return {
            "id": str(self.id),
            "file_id": str(self.file.id) if self.file else None,
            "version_number": self.version_number,
            "content_hash": self.content_hash,
            "size": self.size_bytes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "uploaded_by": str(self.uploaded_by.id) if self.uploaded_by else None
        }

class File(me.Document):
    name = me.StringField(required=True)
    owner = me.ReferenceField(User, required=True)
    parent_folder = me.ReferenceField(Folder, null=True, default=None)
    current_version = me.ReferenceField(FileVersion, null=True, default=None)
    created_at = me.DateTimeField(default=datetime.utcnow)
    updated_at = me.DateTimeField(default=datetime.utcnow)
    deleted = me.BooleanField(default=False)

    meta = {
        'collection': 'files',
        'indexes': ['owner', 'parent_folder', 'deleted', 'updated_at']
    }

    def to_dict(self):
        ver = self.current_version
        return {
            "id": str(self.id),
            "name": self.name,
            "owner": str(self.owner.id) if self.owner else None,
            "parent_id": str(self.parent_folder.id) if self.parent_folder else None,
            "type": "file",
            "current_version_id": str(ver.id) if ver else None,
            "version_number": ver.version_number if ver else 1,
            "content_hash": ver.content_hash if ver else None,
            "size": ver.size_bytes if ver else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "deleted": self.deleted
        }
