class RasterNotConfiguredError(RuntimeError):
    """El backend no tiene un GeoTIFF disponible."""


class InvalidGeoJSONError(ValueError):
    """El payload GeoJSON no cumple el contrato de la API."""


class SupabaseNotConfiguredError(RuntimeError):
    """Faltan credenciales o configuración de Supabase."""


class OrthomosaicNotFoundError(RuntimeError):
    """No existe el ortomosaico solicitado."""


class RoiAnalysisNotFoundError(RuntimeError):
    """No existe el análisis zonal solicitado para el ROI."""
