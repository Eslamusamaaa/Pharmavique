"""Counts of what is missing in the catalog, for the operator's data-quality board."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pharmavique.catalog.contracts.queries import CatalogQualityStats, ListQuality
from pharmavique.shared_kernel.market import Market

_PRODUCTS = text(
    """
    SELECT
      count(*) AS products,
      count(*) FILTER (WHERE listing_status = 'listed') AS listed,
      count(*) FILTER (WHERE listing_status = 'withdrawn') AS withdrawn,
      count(*) FILTER (WHERE listing_status = 'listed' AND price_amount IS NULL) AS no_price,
      count(*) FILTER (
        WHERE listing_status = 'listed' AND jsonb_array_length(data->'ingredients') = 0
      ) AS no_ingredients,
      count(*) FILTER (
        WHERE listing_status = 'listed'
          AND EXISTS (
            SELECT 1 FROM jsonb_array_elements(data->'ingredients') i
            WHERE jsonb_typeof(i->'strength') IS DISTINCT FROM 'string'
          )
      ) AS missing_strength,
      count(*) FILTER (
        WHERE listing_status = 'listed'
          AND jsonb_typeof(data->'marketing_company') IS DISTINCT FROM 'object'
          AND jsonb_array_length(data->'manufacturers') = 0
      ) AS no_manufacturer
    FROM catalog.products
    WHERE market = :market
    """
)

_PICTURES = text(
    """
    SELECT
      count(*) FILTER (WHERE pic.kind = 'real') AS real_pictures,
      count(*) FILTER (WHERE pic.kind = 'generated') AS generated_pictures,
      count(*) FILTER (WHERE pic.register_number IS NULL) AS no_picture
    FROM catalog.products p
    LEFT JOIN catalog.product_pictures pic
      ON pic.market = p.market AND pic.register_number = p.register_number
    WHERE p.market = :market AND p.listing_status = 'listed'
    """
)

_LISTS = text(
    """
    WITH best AS (
      SELECT list_name, row_key, bool_or(confidence = 'matched') AS has_matched
      FROM catalog.source_list_links
      WHERE market = :market
      GROUP BY list_name, row_key
    )
    SELECT r.list_name,
           count(*) AS total,
           count(*) FILTER (WHERE b.has_matched) AS matched,
           count(*) FILTER (WHERE b.has_matched IS FALSE) AS possible,
           count(*) FILTER (WHERE b.row_key IS NULL) AS unlinked,
           max(r.provenance_fetched_at) AS fetched
    FROM catalog.source_list_rows r
    LEFT JOIN best b ON b.list_name = r.list_name AND b.row_key = r.row_key
    GROUP BY r.list_name
    ORDER BY r.list_name
    """
)


class SqlAlchemyQualityReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def quality_stats(self, market: Market) -> CatalogQualityStats:
        params = {"market": market.value}
        async with self._session_factory() as session:
            products = (await session.execute(_PRODUCTS, params)).one()
            pictures = (await session.execute(_PICTURES, params)).one()
            lists = (await session.execute(_LISTS, params)).all()
        return CatalogQualityStats(
            market=market,
            products=products.products,
            listed=products.listed,
            withdrawn=products.withdrawn,
            listed_without_price=products.no_price,
            listed_without_ingredients=products.no_ingredients,
            listed_with_missing_strength=products.missing_strength,
            listed_without_manufacturer=products.no_manufacturer,
            listed_with_real_picture=pictures.real_pictures,
            listed_with_generated_picture=pictures.generated_pictures,
            listed_without_picture=pictures.no_picture,
            lists=tuple(
                ListQuality(
                    list_name=row.list_name,
                    rows=row.total,
                    linked_matched=row.matched,
                    linked_possible=row.possible,
                    unlinked=row.unlinked,
                    last_fetched_at=row.fetched,
                )
                for row in lists
            ),
        )
