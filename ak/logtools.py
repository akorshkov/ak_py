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


_BY_VERBOCITY_LOG_LEVELS = {
    -1: logging.ERROR,
    0: logging.WARNING,
    1: logging.INFO,
    2: logging.DEBUG,
}

def logs_configure(
        verbocity=0, *,
        level=None,
        filename=None, file_log_level=None,
        use_colors=True, use_logfile_colors=True,
        log_colors=None):
    """High-level method for configuring logging in common scenarios.

    By default configutres logging with predefined colors, stderr output, warnings
    level.

    Arguments (all arguments are optional):
    - verbocity: integer verbocity level (f.e. if specified by command line
        arguments '-v', '-vv', etc.). Converted to log level according to following
        rules:
        verbocity     level
        -1            logging.ERROR
        0  (default)  logging.WARNING
        1             logging.INFO
        2             logging.DEBUG
        Can be overriden by explicitely specified log level.
    - level: level of stderr logs. Overrides log level corresponding to verbocity argument.
    - filename:  name of log file.
    - file_log_level: level of log file. Default is DEBUG, ignored if filename is
        not specified.
    - use_colors, use_logfile_colors - by default both values are 'True'. (So, you
        can 'tail -f' log file and see debug logs in separate terminal)
    - log_colors: optional dictionary {logging.LEVEL: color_obj}
        This argument can be specified to override predefined loglevel colors.
        Check help(ColorFmt.make) for possible values 'color_obj'.
    """
    use_logfile = filename is not None

    v_log_level = _BY_VERBOCITY_LOG_LEVELS.get(verbocity, None)
    if v_log_level is None:
        # specified verbocity is too high or too low
        v_log_level = logging.ERROR if verbocity < -1 else logging.DEBUG

    if level is None:
        level = v_log_level
    if file_log_level is None:
        file_log_level = logging.DEBUG

    if use_colors or use_logfile_colors:
        register_colored_levelnames(log_colors=log_colors)

    fmt_color = "[%(asctime)s] %(levelname_c)s:%(name)s:%(message)s"
    fmt_no_color = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"

    stderr_formatter = logging.Formatter(fmt_color if use_colors else fmt_no_color)

    # stderr log
    stderr_handler = logging.StreamHandler()
    stderr_handler.setLevel(level)
    stderr_handler.setFormatter(stderr_formatter)

    root_logger_level = level
    if use_logfile:
        root_logger_level = min(level, file_log_level)
    root_logger = logging.getLogger('')
    root_logger.setLevel(root_logger_level)
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
        file_handler.setLevel(file_log_level)

        root_logger.addHandler(file_handler)
