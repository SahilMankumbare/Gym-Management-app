"""


import os
import sys

# TODO: change this to the folder where you uploaded the project.
PROJECT_DIR = "/home/YOUR_USERNAME/gymbroch"

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
os.chdir(PROJECT_DIR)

from app import app as application  # noqa: E402

if __name__ == "__main__":
    application.run(debug=False, host="0.0.0.0", port=5000)




    This is made to deploy on pythonanywhere application.
