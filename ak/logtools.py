"""Helpers for logging configuration."""

import logging
from .color import ColorFmt


_PREDEFINED_LOGLEVEL_COLORS = {
    logging.DEBUG:    ColorFmt('BLUE'),
    logging.INFO:     ColorFmt('GREEN'),
    logging.WARNING:  ColorFmt('MAGENTA'),
    logging.ERROR:    ColorFmt('RED'),
    logging.CRITICAL: ColorFmt(None, bg_color='RED'),
}


def register_colored_levelnames(
        *,
        log_colors=None,
        use_colors=True):
    """Configure logging, so that each record contains 'levelname_c' property.

    This property contains colored name of log level and can be used by
    logging.Formatter(s) to produce logs with colored loglevel names.

    Arguments:
    - log_colors: optional dictionary {logging.LEVEL: color_obj}
        This argument can be specified to override predefined loglevel colors.
        Check help(ColorFmt.make) for possible values 'color_obj'.
    - use_colors: if specified, all other arguments are ignored, and
        record's 'levelname_c' attributes will contain level names w/o
        any color effects.
    """
    if log_colors is None:
        log_colors = {}

    def _mk_color_fmt(log_level, use_colors):
        # create ColorFmt for coloring log level name. Color is taken either
        # from 'log_colors' argument, or from predefined colors dictionary.
        try:
            color_obj = log_colors[log_level]
        except KeyError:
            color_obj = _PREDEFINED_LOGLEVEL_COLORS[log_level]
        return ColorFmt.make(color_obj, use_colors)

    c_level_names = {  # {log_level: colored_name}
        log_level: str(
            _mk_color_fmt(log_level, use_colors)(logging.getLevelName(log_level))
        )
        for log_level in log_colors.keys() | _PREDEFINED_LOGLEVEL_COLORS.keys()
    }

    old_record_factory = logging.getLogRecordFactory()

    def record_factory(*args, **kwargs):
        """Record factory for logging: adds 'levelname_c' attribute to log records"""
        record = old_record_factory(*args, **kwargs)
        # if some custom loglevel is used and there are no format rules for it
        # then levelname_c will be same as levelname:
        record.levelname_c = c_level_names.get(record.levelno, record.levelname)
        return record

    logging.setLogRecordFactory(record_factory)


def log_configure(
        level=None, *,
        filename=None, use_colors=True, use_logfile_colors=True,
        log_colors=None):
    """High-level method for configuring logging in common scenarios.

    By default configutres logging with predefined colors, stderr output, debug
    level.

    Arguments:
    - level: (optional) level of stderr logs. Default value depends on if
        'filename' is specified. 'ERROR' if filename is specified,
        'DEBUG' othrewise.
    - 'filename' is specified, debug logs are saved to the file. Affects default
        value of 'value' argument.
    - use_colors, use_logfile_colors - by default both values are 'True'. (So, you
        can 'tail -f' log file and see debug logs in separate terminal)
    - log_colors: optional dictionary {logging.LEVEL: color_obj}
        This argument can be specified to override predefined loglevel colors.
        Check help(ColorFmt.make) for possible values 'color_obj'.
    """
    use_logfile = filename is not None

    if level is None:
        level = logging.ERROR if use_logfile else logging.DEBUG

    if use_colors or use_logfile_colors:
        register_colored_levelnames(log_colors=log_colors)

    fmt_color = "[%(asctime)s] %(levelname_c)s:%(name)s:%(message)s"
    fmt_no_color = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"

    stderr_formatter = logging.Formatter(fmt_color if use_colors else fmt_no_color)

    # stderr log
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(stderr_formatter)

    root_logger = logging.getLogger('')
    root_logger.setLevel(logging.DEBUG if use_colors else level)
    root_logger.addHandler(stderr_handler)

    # log file
    if use_logfile:
        if use_colors == use_logfile_colors:
            file_formatter = stderr_formatter
        else:
            file_formatter = logging.Formatter(
                fmt_color if use_logfile_colors else fmt_no_color)

        file_handler = logging.FileHandler(filename)
        file_handler.setFormatter(file_formatter)
        file_handler.setLevel(logging.DEBUG)

        root_logger.addHandler(file_handler)
