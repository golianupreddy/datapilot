from __future__ import annotations

SCHEMA_DOCS: dict[str, dict] = {
    "categories": {
        "description": "Product categories: Beverages, Condiments, Confections, Dairy Products, Grains/Cereals, Meat/Poultry, Produce, Seafood.",
        "columns": {
            "category_id": "smallint, PK",
            "category_name": "text, e.g. 'Beverages'",
            "description": "text, category description",
        },
        "synonyms": ["category", "product category", "product line", "product type"],
    },
    "customers": {
        "description": "Customer companies that place orders.",
        "columns": {
            "customer_id": "char(5), PK, uppercase code like 'ALFKI'",
            "company_name": "text",
            "contact_name": "text",
            "contact_title": "text",
            "address": "text",
            "city": "text",
            "region": "text, often NULL",
            "postal_code": "text",
            "country": "text, e.g. 'Germany', 'USA', 'UK', 'France'",
            "phone": "text",
            "fax": "text",
        },
        "synonyms": ["customer", "client", "buyer", "account", "company"],
    },
    "employees": {
        "description": "Company employees, mainly sales representatives who handle orders.",
        "columns": {
            "employee_id": "smallint, PK",
            "last_name": "text",
            "first_name": "text",
            "title": "text, e.g. 'Sales Representative'",
            "title_of_courtesy": "text",
            "birth_date": "date",
            "hire_date": "date",
            "address": "text",
            "city": "text",
            "region": "text",
            "postal_code": "text",
            "country": "text",
            "home_phone": "text",
            "extension": "text",
            "notes": "text",
            "reports_to": "smallint, FK -> employees.employee_id (the employee's manager)",
        },
        "synonyms": ["employee", "salesperson", "sales rep", "representative", "staff", "manager", "seller", "worker"],
    },
    "orders": {
        "description": "Order headers: who ordered, which employee handled it, dates, shipping details and freight cost.",
        "columns": {
            "order_id": "smallint, PK",
            "customer_id": "char(5), FK -> customers.customer_id",
            "employee_id": "smallint, FK -> employees.employee_id",
            "order_date": "date",
            "required_date": "date, date the customer wanted delivery",
            "shipped_date": "date, NULL if not shipped yet",
            "ship_via": "smallint, FK -> shippers.shipper_id",
            "freight": "real, shipping cost",
            "ship_name": "text",
            "ship_address": "text",
            "ship_city": "text",
            "ship_region": "text",
            "ship_postal_code": "text",
            "ship_country": "text, destination country",
        },
        "synonyms": ["order", "purchase", "shipment", "shipping", "freight", "delivery", "late", "delayed", "shipped", "ship"],
    },
    "order_details": {
        "description": "Order line items: one row per product on an order, with the price, quantity and discount at time of sale. Use this table for revenue and units sold.",
        "columns": {
            "order_id": "smallint, FK -> orders.order_id (part of PK)",
            "product_id": "smallint, FK -> products.product_id (part of PK)",
            "unit_price": "real, price charged per unit",
            "quantity": "smallint, units sold",
            "discount": "real, fraction between 0 and 1 (0.05 = 5%)",
        },
        "synonyms": ["line item", "revenue", "sales", "quantity", "discount", "units sold", "amount", "total", "income", "turnover"],
    },
    "products": {
        "description": "Product catalog with prices, stock levels, supplier and category.",
        "columns": {
            "product_id": "smallint, PK",
            "product_name": "text",
            "supplier_id": "smallint, FK -> suppliers.supplier_id",
            "category_id": "smallint, FK -> categories.category_id",
            "quantity_per_unit": "text, e.g. '10 boxes x 20 bags'",
            "unit_price": "real, current list price",
            "units_in_stock": "smallint",
            "units_on_order": "smallint",
            "reorder_level": "smallint",
            "discontinued": "integer flag, 1 = discontinued, 0 = active",
        },
        "synonyms": ["product", "item", "goods", "stock", "inventory", "price", "discontinued", "reorder"],
    },
    "shippers": {
        "description": "Shipping companies: Speedy Express, United Package, Federal Shipping.",
        "columns": {
            "shipper_id": "smallint, PK",
            "company_name": "text",
            "phone": "text",
        },
        "synonyms": ["shipper", "shipping company", "carrier", "courier", "logistics", "freight company"],
    },
    "suppliers": {
        "description": "Companies that supply the products.",
        "columns": {
            "supplier_id": "smallint, PK",
            "company_name": "text",
            "contact_name": "text",
            "contact_title": "text",
            "address": "text",
            "city": "text",
            "region": "text",
            "postal_code": "text",
            "country": "text",
            "phone": "text",
            "fax": "text",
            "homepage": "text",
        },
        "synonyms": ["supplier", "vendor", "provider", "source"],
    },
    "region": {
        "description": "Four sales regions: Eastern, Western, Northern, Southern.",
        "columns": {
            "region_id": "smallint, PK",
            "region_description": "text, e.g. 'Eastern'",
        },
        "synonyms": ["region", "sales region", "area"],
    },
    "territories": {
        "description": "Sales territories (US cities) each belonging to a region.",
        "columns": {
            "territory_id": "text, PK",
            "territory_description": "text, city name",
            "region_id": "smallint, FK -> region.region_id",
        },
        "synonyms": ["territory", "territories", "sales territory", "district"],
    },
    "employee_territories": {
        "description": "Bridge table: which employees cover which territories.",
        "columns": {
            "employee_id": "smallint, FK -> employees.employee_id",
            "territory_id": "text, FK -> territories.territory_id",
        },
        "synonyms": ["employee territory", "coverage", "assigned territory"],
    },
}

ALL_TABLES: list[str] = list(SCHEMA_DOCS)
ALLOWED_TABLES: set[str] = set(SCHEMA_DOCS)

JOIN_EDGES: list[tuple[str, str, str]] = [
    ("orders", "customers", "orders.customer_id = customers.customer_id"),
    ("orders", "employees", "orders.employee_id = employees.employee_id"),
    ("orders", "shippers", "orders.ship_via = shippers.shipper_id"),
    ("order_details", "orders", "order_details.order_id = orders.order_id"),
    ("order_details", "products", "order_details.product_id = products.product_id"),
    ("products", "categories", "products.category_id = categories.category_id"),
    ("products", "suppliers", "products.supplier_id = suppliers.supplier_id"),
    ("employee_territories", "employees", "employee_territories.employee_id = employees.employee_id"),
    ("employee_territories", "territories", "employee_territories.territory_id = territories.territory_id"),
    ("territories", "region", "territories.region_id = region.region_id"),
    ("employees", "employees", "employees.reports_to = employees.employee_id  (self-join to get the manager)"),
]

BUSINESS_RULES = """- Revenue / sales amount = SUM(order_details.unit_price * order_details.quantity * (1 - order_details.discount)).
- order_details.discount is a fraction (0.05 means 5%).
- The data covers orders from 1996-07-04 to 1998-05-06. NEVER use CURRENT_DATE or NOW(). For "last year", "latest" or "most recent",
  use the data itself, e.g. (SELECT MAX(order_date) FROM orders). Years in the data: 1996, 1997, 1998.
- A late order is one where shipped_date > required_date. An unshipped order has shipped_date IS NULL.
- Employee full name = first_name || ' ' || last_name.
- products.discontinued is an integer flag: 1 = discontinued, 0 = active.
- Postgres ROUND needs numeric: ROUND((expression)::numeric, 2).
- Use the exact spellings of values in the data (e.g. country 'USA', 'UK'); use ILIKE for text matching when unsure about case.
- Number of orders = COUNT(DISTINCT orders.order_id) when joining to order_details."""


def render_table(name: str) -> str:
    d = SCHEMA_DOCS[name]
    cols = "\n".join(f"    - {c}: {t}" for c, t in d["columns"].items())
    return f"TABLE {name}: {d['description']}\n{cols}"


def render_schema(tables: list[str]) -> str:
    chosen = set(tables)
    ordered = [t for t in ALL_TABLES if t in chosen]
    parts = [render_table(t) for t in ordered]
    joins = [cond for a, b, cond in JOIN_EDGES if a in chosen and b in chosen]
    if joins:
        parts.append("JOIN KEYS:\n" + "\n".join(f"    - {j}" for j in joins))
    return "\n\n".join(parts)


def embedding_text(name: str) -> str:
    d = SCHEMA_DOCS[name]
    cols = "; ".join(f"{c} ({t})" for c, t in d["columns"].items())
    return f"Table {name}. {d['description']} Columns: {cols}. Also known as: {', '.join(d['synonyms'])}."


TABLE_OVERVIEW: str = "\n".join(f"- {n}: {d['description']}" for n, d in SCHEMA_DOCS.items())
