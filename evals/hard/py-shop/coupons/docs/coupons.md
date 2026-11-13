# Coupon redemption

Marketing runs limited coupons with affiliate partners ("first 500 customers get 20% off").

## Requirements

1. A customer applies a coupon code to their cart (`POST /orders/<id>/coupon`), case-insensitive.
2. A coupon is valid through the end of its `valid_until` day, store time (Europe/Berlin).
3. `min_subtotal` applies to the cart subtotal **before** the discount.
4. `max_uses` caps total redemptions across all customers. It must never be exceeded, even when
   many customers check out at the same moment (launch traffic is spiky). `max_uses` empty means
   unlimited. **All coupons that exist today are unlimited and must keep working.**
5. One redemption per customer per coupon.
6. The discount is `percent_off` of the subtotal, rounded half up to the cent.
7. Coupon descriptions are written by affiliate partners in the partner portal and shown on the
   cart page.
