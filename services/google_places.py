"""
Google Places API service for place search operations.

This module provides a reusable service for searching places using
Google Places API (New). It supports both single and batch queries.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from logging_config import get_logger

logger = get_logger(__name__)

# Google Places API (New) endpoint
PLACES_API_BASE_URL = "https://places.googleapis.com/v1/places:searchText"

# Fields to request from the API
DEFAULT_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.rating",
    "places.userRatingCount",
    "places.types",
    "places.googleMapsUri",
    "places.businessStatus",
])


@dataclass
class PlaceSearchQuery:
    """
    Input structure for a place search query.

    Attributes:
        query: The place name or text to search for
        location_hint: Optional location context (e.g., "Tokyo, Japan")
        language: Language code for results (default: "en")
        max_results: Maximum number of results to return (default: 5)
    """

    query: str
    location_hint: Optional[str] = None
    language: str = "en"
    max_results: int = 5

    def build_search_text(self) -> str:
        """Build the full search text including location hint."""
        if self.location_hint:
            return f"{self.query}, {self.location_hint}"
        return self.query


@dataclass
class PlaceSearchResult:
    """
    Output structure for a place search result.

    Attributes:
        place_id: Google Place ID
        name: Display name of the place
        formatted_address: Full formatted address
        google_maps_url: Direct link to Google Maps
        rating: Average rating (0-5 scale)
        user_ratings_total: Total number of user ratings
        types: List of place types (e.g., ["restaurant", "food"])
        business_status: Business operational status
    """

    place_id: str
    name: str
    formatted_address: str
    google_maps_url: str
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    types: List[str] = field(default_factory=list)
    business_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "place_id": self.place_id,
            "name": self.name,
            "formatted_address": self.formatted_address,
            "google_maps_url": self.google_maps_url,
            "rating": self.rating,
            "user_ratings_total": self.user_ratings_total,
            "types": self.types,
            "business_status": self.business_status,
        }


class GooglePlacesService:
    """
    Service for searching places using Google Places API (New).

    This service provides methods for searching places by text query,
    supporting both single and batch operations.

    Example:
        service = GooglePlacesService(api_key="your-api-key")
        results = await service.search_place(
            PlaceSearchQuery(query="Starbucks", location_hint="Tokyo")
        )
    """

    def __init__(self, api_key: str, timeout: float = 30.0):
        """
        Initialize the Google Places service.

        Args:
            api_key: Google Places API key
            timeout: Request timeout in seconds
        """
        self._api_key = api_key
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "Content-Type": "application/json",
                    "X-Goog-Api-Key": self._api_key,
                    "X-Goog-FieldMask": DEFAULT_FIELD_MASK,
                },
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def search_place(
        self, query: PlaceSearchQuery
    ) -> List[PlaceSearchResult]:
        """
        Search for a single place.

        Args:
            query: The search query parameters

        Returns:
            List of matching place results (may be empty if no matches)
        """
        client = await self._get_client()

        search_text = query.build_search_text()

        request_body = {
            "textQuery": search_text,
            "languageCode": query.language,
            "maxResultCount": query.max_results,
        }

        logger.debug(
            "Searching Google Places API",
            extra={
                "search_text": search_text,
                "language": query.language,
                "max_results": query.max_results,
            },
        )

        try:
            response = await client.post(PLACES_API_BASE_URL, json=request_body)
            response.raise_for_status()
            data = response.json()

            places = data.get("places", [])
            results = []

            for place in places:
                result = self._parse_place(place)
                if result:
                    results.append(result)

            logger.info(
                "Google Places search completed",
                extra={
                    "query": query.query,
                    "results_count": len(results),
                },
            )

            return results

        except httpx.HTTPStatusError as e:
            logger.error(
                "Google Places API HTTP error",
                extra={
                    "status_code": e.response.status_code,
                    "query": query.query,
                    "response_text": e.response.text[:500],
                },
            )
            raise
        except httpx.RequestError as e:
            logger.error(
                "Google Places API request error",
                extra={
                    "query": query.query,
                    "error": str(e),
                },
            )
            raise

    async def search_places_batch(
        self, queries: List[PlaceSearchQuery]
    ) -> List[List[PlaceSearchResult]]:
        """
        Search for multiple places in batch.

        Args:
            queries: List of search query parameters

        Returns:
            List of result lists, one for each query (in same order)
        """
        results = []
        for query in queries:
            try:
                place_results = await self.search_place(query)
                results.append(place_results)
            except Exception as e:
                logger.warning(
                    "Batch search failed for query",
                    extra={
                        "query": query.query,
                        "error": str(e),
                    },
                )
                # Return empty list for failed queries
                results.append([])

        return results

    def _parse_place(self, place_data: Dict[str, Any]) -> Optional[PlaceSearchResult]:
        """
        Parse a place from the API response.

        Args:
            place_data: Raw place data from API

        Returns:
            PlaceSearchResult or None if parsing fails
        """
        try:
            # Extract place ID from the resource name (format: places/PLACE_ID)
            resource_name = place_data.get("id", "")
            place_id = resource_name

            # Get display name
            display_name_data = place_data.get("displayName", {})
            name = display_name_data.get("text", "Unknown")

            # Get address
            formatted_address = place_data.get("formattedAddress", "")

            # Get Google Maps URL
            google_maps_url = place_data.get("googleMapsUri", "")

            # Get rating info
            rating = place_data.get("rating")
            user_ratings_total = place_data.get("userRatingCount")

            # Get types
            types = place_data.get("types", [])

            # Get business status
            business_status = place_data.get("businessStatus")

            return PlaceSearchResult(
                place_id=place_id,
                name=name,
                formatted_address=formatted_address,
                google_maps_url=google_maps_url,
                rating=rating,
                user_ratings_total=user_ratings_total,
                types=types,
                business_status=business_status,
            )
        except Exception as e:
            logger.warning(
                "Failed to parse place data",
                extra={"error": str(e), "place_data_keys": list(place_data.keys())},
            )
            return None
