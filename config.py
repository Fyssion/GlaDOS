import yaml


# NOTE: This is not a config file
# This is only a helper class for the actual
# config file


class MissingOption(Exception):
    pass


class Config:
    """config.yml helper class"""

    def __init__(self, file_path):
        self._file_path = file_path

        with open(file_path, "r") as config:
            self._data = yaml.safe_load(config)

        # Required config stuff
        self.bot_token = self._get("bot-token")  # Bot token

        self.database_uri = self._get("database-uri")

        self.debug = self._get("debug", optional=True, default=False)

    def _get(self, key, *, optional=False, default=None):
        # Set the attribute
        value = self._data.get(key) or default

        # Check if it's missing and not optional
        if not optional and not value:
            raise MissingOption(f"Missing option '{key}'. This option is required.")

        return value
