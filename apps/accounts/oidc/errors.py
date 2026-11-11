"""Errors whose response body is ``{"code": <fixed code>, ...}``.

The code vocabulary is fixed so no response names a claim value, a resolved address or an
exception message.
"""

from rest_framework import status
from rest_framework.exceptions import APIException


class CodedError(APIException):
    status_code = status.HTTP_400_BAD_REQUEST

    def __init__(self, code, *, status_code=None, **extra):
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail={"code": code, **extra})
