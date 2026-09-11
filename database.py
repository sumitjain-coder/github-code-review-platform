"""
DATABASE SETUP
---------------
This creates the single shared "db" object that our models.py file
and app.py will both use. Keeping this separate avoids a common
Flask/SQLAlchemy tangle called "circular imports."
"""

from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
