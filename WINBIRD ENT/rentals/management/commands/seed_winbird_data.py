from decimal import Decimal

from django.core.management.base import BaseCommand

from rentals.models import Category, Inventory, PriceOption, RentalItem


ITEMS = [
    ("Cheese Tent", [("Standard", Decimal("600.00"))]),
    ("Caravan Chairs", [("Standard", Decimal("7.00"))]),
    ("Green Carpet", [("Standard", Decimal("300.00"))]),
    ("Canopies", [("Shooting", Decimal("70.00")), ("Normal", Decimal("40.00"))]),
    ("Foldable Chairs", [("Standard", Decimal("3.00"))]),
    ("Tables", [("Standard", Decimal("20.00"))]),
    ("Mattress", [("Standard", Decimal("3.00"))]),
    ("Bridal Chair", [("Standard", Decimal("200.00"))]),
    ("Cake Stand", [("Standard", Decimal("50.00"))]),
    ("Table Cloth", [("Premium", Decimal("20.00")), ("Standard", Decimal("15.00"))]),
    ("Chair Covers", [("Standard", Decimal("2.50"))]),
    ("Under Plates", [("Basic", Decimal("3.00")), ("Mid", Decimal("4.00")), ("Premium", Decimal("5.00"))]),
    ("Flower Vase", [("Classic", Decimal("8.00")), ("Premium", Decimal("10.00"))]),
    ("Flowers", [("Standard", Decimal("15.00"))]),
]


class Command(BaseCommand):
    help = "Seed the WINBIRD ENTERPRISE rental catalog."

    def handle(self, *args, **options):
        category, _ = Category.objects.get_or_create(name="Default")
        created_items = 0

        for item_name, prices in ITEMS:
            item, created = RentalItem.objects.get_or_create(
                name=item_name,
                defaults={"category": category, "is_active": True},
            )
            if created:
                created_items += 1

            Inventory.objects.get_or_create(
                rental_item=item,
                defaults={"quantity_total": 0, "quantity_available": 0},
            )

            for index, (label, amount) in enumerate(prices):
                PriceOption.objects.get_or_create(
                    rental_item=item,
                    label=label,
                    amount=amount,
                    defaults={"is_default": index == 0, "is_active": True},
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Catalog ready. Created {created_items} new item(s); quantities remain at 0 until updated."
            )
        )
