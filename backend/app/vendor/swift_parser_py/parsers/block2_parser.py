import re
from typing import Dict, Any

def parse(input_text: str) -> Dict[str, Any]:
    """
    Parse Block 2 of a SWIFT message

    Args:
        input_text: The content of Block 2

    Returns:
        Dictionary with parsed data
    """
    result = {
        "content": input_text,
        "block_id": 2
    }

    # Pattern for output messages
    output_pattern = re.compile(
        r'O(?P<MsgType>\d{3})(?P<InputTime>\d{4})(?P<InputDate>\d{6})(?P<Bic>\w*?)(?P<Session>\w{4})(?P<Sequence>\w{6})(?P<OutputDate>\d{6})(?P<OutputTime>\d{4})(?P<Prio>[SNU])'
    )
    match = output_pattern.match(input_text)

    if match:
        result["direction"] = "O"
        result["msg_type"] = match.group("MsgType")
        result["input_time"] = match.group("InputTime")
        result["input_date"] = match.group("InputDate")
        result["bic"] = match.group("Bic")
        result["session_number"] = match.group("Session")
        result["sequence_number"] = match.group("Sequence")
        result["output_date"] = match.group("OutputDate")
        result["output_time"] = match.group("OutputTime")
        result["prio"] = match.group("Prio")
        return result

    # Pattern for input messages with timestamp
    # Format: I + MsgType(3 digits) + InputTime(4 digits) + InputDate(6 digits) + BIC(12 chars) +
    #         SessionNumber(4 digits) + SequenceNumber(6 digits) + OutputDate(6 digits) + OutputTime(4 digits) + Priority(1 char)
    input_pattern_with_timestamp = re.compile(
        r'I(?P<MsgType>\d{3})(?P<InputTime>\d{4})(?P<InputDate>\d{6})(?P<Bic>[A-Z0-9]{12})(?P<Session>\d{4})(?P<Sequence>\d{6})(?P<OutputDate>\d{6})(?P<OutputTime>\d{4})(?P<Prio>[SNU])(?P<MonitoringField>[123])?(?P<Obsolescence>\d{3})?'
    )
    match = input_pattern_with_timestamp.match(input_text)

    if match:
        result["direction"] = "I"
        result["msg_type"] = match.group("MsgType")
        result["input_time"] = match.group("InputTime")
        result["input_date"] = match.group("InputDate")
        result["bic"] = match.group("Bic")
        result["session_number"] = match.group("Session")
        result["sequence_number"] = match.group("Sequence")
        result["output_date"] = match.group("OutputDate")
        result["output_time"] = match.group("OutputTime")
        result["prio"] = match.group("Prio")

        monitoring_field = match.group("MonitoringField")
        if monitoring_field:
            result["monitoring_field"] = monitoring_field

        obsolescence = match.group("Obsolescence")
        if obsolescence:
            result["obsolescence"] = obsolescence

        return result

    # Pattern for simple input messages (without timestamp)
    input_pattern = re.compile(
        r'I(?P<MsgType>\d{3})(?P<Bic>[A-Z0-9]{12})(?P<Prio>[SNU])(?P<MonitoringField>[123])?(?P<Obsolescence>\d{3})?'
    )
    match = input_pattern.match(input_text)

    if match:
        result["direction"] = "I"
        result["msg_type"] = match.group("MsgType")
        result["bic"] = match.group("Bic")
        result["prio"] = match.group("Prio")

        monitoring_field = match.group("MonitoringField")
        if monitoring_field:
            result["monitoring_field"] = monitoring_field

        obsolescence = match.group("Obsolescence")
        if obsolescence:
            result["obsolescence"] = obsolescence

    return result