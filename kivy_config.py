import os

# Get the environment variable
env = os.getenv("ENVIRONMENT")

# Configure Kivy for headless mode in CI environment
if env == "GITLAB":
    # Set Kivy environment variables before any Kivy imports
    os.environ["KIVY_WINDOW"] = "sdl2"
    os.environ["KIVY_GL_BACKEND"] = "gl"
    os.environ["KIVY_GRAPHICS"] = "null"
    os.environ["KIVY_AUDIO"] = "sdl2"
    os.environ["DISPLAY"] = ":99"  # Virtual display for CI
