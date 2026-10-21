import os

# Change these to match your MySQL install, or set them as environment variables.
DB_HOST = os.environ.get("GC_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("GC_DB_PORT", "3306"))
DB_USER = os.environ.get("GC_DB_USER", "root")
DB_PASSWORD = os.environ.get("GC_DB_PASSWORD", "")
DB_NAME = os.environ.get("GC_DB_NAME", "green_campus_db")

SECRET_KEY = os.environ.get("GC_SECRET_KEY", "change-me-before-deploying")
