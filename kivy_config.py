import os
import sys

# Get the environment variable
env = os.getenv("ENVIRONMENT")

# Configure Kivy for headless mode
if env == "GITLAB":
    print("Configuring Kivy for GitLab CI environment", file=sys.stderr)
    # Set Kivy environment variables before any Kivy imports
    os.environ["KIVY_WINDOW"] = "dummy"
    os.environ["KIVY_GL_BACKEND"] = "mock"
    os.environ["KIVY_AUDIO"] = "sdl2"
    os.environ["KIVY_NO_CONSOLELOG"] = "1"
    os.environ["KIVY_NO_FILELOG"] = "1"
    print("Kivy environment configured for headless mode", file=sys.stderr)
else:
    print(f"Environment: {env}, using default Kivy configuration", file=sys.stderr)
    # Only set headless mode for testing environments
    # Check if we're in a test environment (pytest sets PYTEST_CURRENT_TEST)
    if "PYTEST_CURRENT_TEST" in os.environ:
        print(
            "Detected pytest environment, configuring for headless mode",
            file=sys.stderr,
        )
        if "KIVY_WINDOW" not in os.environ:
            os.environ["KIVY_WINDOW"] = "dummy"
        if "KIVY_GL_BACKEND" not in os.environ:
            os.environ["KIVY_GL_BACKEND"] = "mock"
        if "KIVY_NO_CONSOLELOG" not in os.environ:
            os.environ["KIVY_NO_CONSOLELOG"] = "1"
    else:
        print(
            "Normal application run detected, keeping default Kivy settings",
            file=sys.stderr,
        )
