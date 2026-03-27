import hashlib
import os

class SecurityManager:
    def __init__(self, salt_file: str = "salt.bin"):
        self.salt_file = salt_file
        self.salt = self._load_or_create_salt()

    def _load_or_create_salt(self) -> bytes:
        if os.path.exists(self.salt_file):
            with open(self.salt_file, "rb") as f:
                return f.read()
        else:
            salt = os.urandom(16)
            with open(self.salt_file, "wb") as f:
                f.write(salt)
            return salt

    def derive_key(self, master_password: str) -> str:
        """Derives a database key from the master password using PBKDF2."""
        key = hashlib.pbkdf2_hmac(
            'sha256',
            master_password.encode('utf-8'),
            self.salt,
            100000  # Iterations
        )
        return key.hex()

    def verify_master_password(self, master_password: str, db_path: str) -> bool:
        """
        Verifies if the master password unlocks the local sqlcipher db.
        If the db doesn't exist yet, any password is valid (initial creation).
        """
        if not os.path.exists(db_path):
            return True # First time setup
            
        key = self.derive_key(master_password)
        try:
            try:
                from pysqlcipher3 import dbapi2 as sqlite
            except ImportError:
                print("Warning: pysqlcipher3 not installed. Falling back to sqlite3 (NO ENCRYPTION for verification check).")
                import sqlite3 as sqlite

            conn = sqlite.connect(db_path)
            cursor = conn.cursor()
            # This is how SQLCipher accepts keys via raw sqlite
            cursor.execute(f"PRAGMA key='{key}'")
            # If the key is wrong, this query will fail with DatabaseError
            cursor.execute("SELECT count(*) FROM sqlite_master")
            cursor.fetchone()
            conn.close()
            return True
        except Exception:
            # Catching generic Exception because sqlite.DatabaseError varies based on the fallback
            return False
