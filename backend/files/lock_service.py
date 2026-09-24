from datetime import datetime, timedelta
import mongoengine as me

from files.models import File
from accounts.models import User

class FileLockService:
    @staticmethod
    def acquire_lock(file: File, user: User, device_id: str, duration_seconds: int = 300) -> bool:
        """
        Attempts to acquire a lock atomically.
        Returns True if acquired or already owned by the same user+device.
        """
        if not device_id:
            return False # device_id is required
            
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=duration_seconds)

        # If it's already locked by this exact user and device, just extend it.
        if file.is_locked and file.lock_owner == user and file.lock_device_id == device_id:
            # Atomic update to extend
            updated = File.objects(
                id=file.id,
                is_locked=True,
                lock_owner=user,
                lock_device_id=device_id
            ).update_one(set__lock_expires_at=expires_at)
            
            if updated:
                file.reload()
                return True

        # Otherwise, attempt to lock it if it's currently unlocked or expired
        updated = File.objects(
            (me.Q(is_locked=False) | me.Q(lock_expires_at__lt=now)),
            id=file.id
        ).update_one(
            set__is_locked=True,
            set__lock_owner=user,
            set__lock_device_id=device_id,
            set__lock_expires_at=expires_at
        )

        if updated:
            file.reload()
            return True
            
        return False

    @staticmethod
    def renew_lock(file: File, user: User, device_id: str, duration_seconds: int = 300) -> bool:
        """
        Renews an existing lock if owned by the user+device.
        """
        if not device_id:
            return False
            
        now = datetime.utcnow()
        expires_at = now + timedelta(seconds=duration_seconds)
        
        updated = File.objects(
            id=file.id,
            is_locked=True,
            lock_owner=user,
            lock_device_id=device_id
        ).update_one(set__lock_expires_at=expires_at)
        
        if updated:
            file.reload()
            return True
        return False

    @staticmethod
    def release_lock(file: File, user: User, device_id: str) -> bool:
        """
        Releases the lock if owned by the user+device.
        """
        if not device_id:
            return False
            
        updated = File.objects(
            id=file.id,
            is_locked=True,
            lock_owner=user,
            lock_device_id=device_id
        ).update_one(
            set__is_locked=False,
            set__lock_owner=None,
            set__lock_device_id=None,
            set__lock_expires_at=None
        )
        
        if updated:
            file.reload()
            return True
        return False

    @staticmethod
    def can_modify(file: File, user: User, device_id: str = None) -> bool:
        """
        Checks if the file can be modified by the given user+device.
        """
        now = datetime.utcnow()
        
        # If not locked or lock has expired, anyone with permission can modify
        if not file.is_locked or (file.lock_expires_at and file.lock_expires_at < now):
            return True
            
        # It is locked and active.
        # The modifier MUST be the lock owner AND have the matching device_id.
        if file.lock_owner == user and device_id and file.lock_device_id == device_id:
            return True
            
        return False

    @staticmethod
    def check_and_clear_expired(file: File):
        """
        Helper to clear expired locks when reading.
        """
        now = datetime.utcnow()
        if file.is_locked and file.lock_expires_at and file.lock_expires_at < now:
            File.objects(id=file.id, lock_expires_at__lt=now).update_one(
                set__is_locked=False,
                set__lock_owner=None,
                set__lock_device_id=None,
                set__lock_expires_at=None
            )
            file.reload()
