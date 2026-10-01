"""POST /api/v1/route/: plan the fuel stops for a drive between two places."""

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.trips.providers.base import NoRouteFoundError, RoutingServiceError, RoutingTimeoutError
from apps.trips.serializers import RouteRequestSerializer, TripPlanSerializer
from apps.trips.services import NoTripPlanError, PointFarFromRoadError, plan_trip


class RouteView(APIView):
    """The driving route, the cheapest fuel stops, and what they cost.

    Bad input is 400. A trip that cannot be planned (no road, a point far from any road, or
    no way to buy fuel) is 422. A routing service that is down is 502, and one that is too
    slow is 504.
    """

    def post(self, request: Request) -> Response:
        incoming = RouteRequestSerializer(data=request.data)
        incoming.is_valid(raise_exception=True)
        try:
            plan = plan_trip(incoming.validated_data["start"], incoming.validated_data["finish"])
        except ValueError as error:
            return _detail(str(error), status.HTTP_400_BAD_REQUEST)
        except (NoRouteFoundError, PointFarFromRoadError, NoTripPlanError) as error:
            return _detail(str(error), status.HTTP_422_UNPROCESSABLE_ENTITY)
        except RoutingTimeoutError as error:
            return _detail(str(error), status.HTTP_504_GATEWAY_TIMEOUT)
        except RoutingServiceError as error:
            return _detail(str(error), status.HTTP_502_BAD_GATEWAY)
        return Response(TripPlanSerializer(plan).data)


def _detail(message: str, status_code: int) -> Response:
    return Response({"detail": message}, status=status_code)
