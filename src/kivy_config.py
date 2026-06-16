import os
import sys

# Get the environment variable
env = os.getenv("ENVIRONMENT")

# Configure Kivy for headless mode in CI or pytest environments
if env == "CI" or "PYTEST_CURRENT_TEST" in os.environ:
    print("Configuring Kivy for headless mode", file=sys.stderr)
    if "KIVY_WINDOW" not in os.environ:
        os.environ["KIVY_WINDOW"] = "dummy"
    if "KIVY_GL_BACKEND" not in os.environ:
        os.environ["KIVY_GL_BACKEND"] = "mock"
    if "KIVY_AUDIO" not in os.environ:
        os.environ["KIVY_AUDIO"] = "sdl2"
    os.environ["KIVY_NO_CONSOLELOG"] = "1"
    os.environ["KIVY_NO_FILELOG"] = "1"
else:
    print(
        "Normal application run detected, keeping default Kivy settings",
        file=sys.stderr,
    )
