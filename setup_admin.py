"""Secure interactive setup or rotation of the single admin account.
Run: python setup_admin.py --email you@example.com
The password is requested invisibly; never put it in a command-line argument.
"""
import argparse
from getpass import getpass

from app import app as flask_app, set_admin_credentials


def main():
    parser = argparse.ArgumentParser(description="Create or rotate the admin credentials")
    parser.add_argument("--email", default="ziyaullahshahid@gmail.com", help="Admin login email")
    args = parser.parse_args()
    password = getpass("New admin password (at least 12 characters): ")
    confirmation = getpass("Confirm new password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match.")
    set_admin_credentials(flask_app.config["DATABASE"], args.email, password)
    print("Admin account configured. Remember to set FLASK_SECRET_KEY before deployment.")


if __name__ == "__main__":
    main()
