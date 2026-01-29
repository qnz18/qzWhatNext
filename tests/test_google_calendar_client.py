from unittest.mock import MagicMock, patch

from qzwhatnext.integrations.google_calendar import GoogleCalendarClient


def test_list_events_in_range_passes_fields_param_to_google_api():
    service = MagicMock()
    events_resource = service.events.return_value

    req = MagicMock()
    req.execute.return_value = {"items": [], "nextPageToken": None}
    # If code accidentally calls req.fields(...), this will record the call.
    req.fields = MagicMock()
    events_resource.list.return_value = req

    with patch("qzwhatnext.integrations.google_calendar.build", return_value=service):
        client = GoogleCalendarClient(credentials=MagicMock(), calendar_id="primary")
        client.list_events_in_range(
            time_min_rfc3339="2026-01-01T00:00:00Z",
            time_max_rfc3339="2026-01-02T00:00:00Z",
            fields="items(start,end,status,extendedProperties(private)),nextPageToken",
        )

    events_resource.list.assert_called_once()
    _, kwargs = events_resource.list.call_args
    assert kwargs.get("calendarId") == "primary"
    assert kwargs.get("timeMin") == "2026-01-01T00:00:00Z"
    assert kwargs.get("timeMax") == "2026-01-02T00:00:00Z"
    assert kwargs.get("fields")
    assert req.fields.call_count == 0

