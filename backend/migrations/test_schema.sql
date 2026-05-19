-- =============================================================
-- Schema Test Suite
-- =============================================================

BEGIN;

-- -----------------------------------------------
-- V001: Departments and Suppliers
-- -----------------------------------------------

-- Departments were pre-seeded
DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM departments) = 6, 'FAIL: departments seed count';
    ASSERT (SELECT COUNT(*) FROM departments WHERE slug = 'fresh-produce') = 1, 'FAIL: fresh-produce missing';
END $$;

-- Supplier insert
INSERT INTO suppliers (name, contact_name, contact_email)
VALUES ('Test Supplier', 'John Doe', 'john@supplier.com');

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM suppliers WHERE name = 'Test Supplier') = 1, 'FAIL: supplier insert';
END $$;

-- -----------------------------------------------
-- V002: Products, Variants, Allergens
-- -----------------------------------------------

-- 14 allergens pre-seeded
DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM allergens) = 14, 'FAIL: allergens seed count';
END $$;

-- Insert a base product
INSERT INTO products (department_id, name, is_age_restricted)
VALUES (1, 'Whole Milk', FALSE);

-- Fixed-price variant
INSERT INTO product_variants (product_id, sku, barcode, name, pricing_mode, sell_price, cost_price)
VALUES (1, 'MILK-2L', '5000000000001', 'Whole Milk 2L', 'fixed', 1.49, 0.80);

-- Weight-based variant
INSERT INTO product_variants (product_id, sku, name, pricing_mode, sell_price, cost_price, unit_of_measure)
VALUES (1, 'MILK-KG', 'Whole Milk per kg', 'weight_based', 2.00, 1.00, 'kg');

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM product_variants WHERE product_id = 1) = 2, 'FAIL: variant insert';
    ASSERT (SELECT pricing_mode FROM product_variants WHERE sku = 'MILK-KG') = 'weight_based', 'FAIL: weight_based mode';
END $$;

-- SKU must be unique
DO $$ BEGIN
    BEGIN
        INSERT INTO product_variants (product_id, sku, name, pricing_mode, sell_price, cost_price)
        VALUES (1, 'MILK-2L', 'Duplicate SKU', 'fixed', 1.49, 0.80);
        ASSERT FALSE, 'FAIL: duplicate SKU should be rejected';
    EXCEPTION WHEN unique_violation THEN
        NULL; -- expected
    END;
END $$;

-- Allergen junction
INSERT INTO product_variant_allergens (variant_id, allergen_id, may_contain)
VALUES (1, (SELECT id FROM allergens WHERE eu_code = 'MLK'), FALSE);

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM product_variant_allergens WHERE variant_id = 1) = 1, 'FAIL: allergen junction';
END $$;

-- -----------------------------------------------
-- V003: Inventory Ledger
-- -----------------------------------------------

-- Stock in
INSERT INTO inventory_ledger (variant_id, department_id, movement_type, quantity)
VALUES (1, 1, 'goods_received', 100);

-- Stock out (sale)
INSERT INTO inventory_ledger (variant_id, department_id, movement_type, quantity)
VALUES (1, 1, 'sale', -5);

DO $$ BEGIN
    ASSERT (SELECT get_variant_stock(1)) = 95, 'FAIL: stock ledger sum';
END $$;

-- Adjustment without reason must fail
DO $$ BEGIN
    BEGIN
        INSERT INTO inventory_ledger (variant_id, department_id, movement_type, quantity, reason)
        VALUES (1, 1, 'adjustment', -10, NULL);
        ASSERT FALSE, 'FAIL: adjustment without reason should be rejected';
    EXCEPTION WHEN check_violation THEN
        NULL; -- expected
    END;
END $$;

-- Adjustment with reason must pass
INSERT INTO inventory_ledger (variant_id, department_id, movement_type, quantity, reason)
VALUES (1, 1, 'adjustment', -2, 'Damaged on shelf — confirmed by manager');

DO $$ BEGIN
    ASSERT (SELECT get_variant_stock(1)) = 93, 'FAIL: stock after adjustment';
END $$;

-- -----------------------------------------------
-- V004: Customers and Loyalty
-- -----------------------------------------------

INSERT INTO customers (first_name, last_name, email, marketing_consent)
VALUES ('Jane', 'Smith', 'jane@example.com', TRUE);

INSERT INTO loyalty_accounts (customer_id)
VALUES (1);

INSERT INTO loyalty_transactions (loyalty_account_id, transaction_type, points)
VALUES (1, 'earn', 100);

INSERT INTO loyalty_transactions (loyalty_account_id, transaction_type, points)
VALUES (1, 'redeem', -30);

DO $$ BEGIN
    ASSERT (SELECT get_loyalty_balance(1)) = 70, 'FAIL: loyalty balance';
END $$;

-- Loyalty adjustment without reason must fail
DO $$ BEGIN
    BEGIN
        INSERT INTO loyalty_transactions (loyalty_account_id, transaction_type, points, reason)
        VALUES (1, 'adjustment', 50, NULL);
        ASSERT FALSE, 'FAIL: loyalty adjustment without reason should be rejected';
    EXCEPTION WHEN check_violation THEN
        NULL; -- expected
    END;
END $$;

-- -----------------------------------------------
-- V005: Orders and Returns
-- -----------------------------------------------

INSERT INTO orders (status, payment_method, subtotal_pence, total_pence, receipt_number)
VALUES ('paid', 'cash', 149, 149, 'RCP-0001');

INSERT INTO order_items (order_id, variant_id, variant_name_snapshot, unit_price_pence, quantity, line_total_pence)
VALUES (1, 1, 'Whole Milk 2L', 149, 1, 149);

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM orders WHERE receipt_number = 'RCP-0001') = 1, 'FAIL: order insert';
    ASSERT (SELECT COUNT(*) FROM order_items WHERE order_id = 1) = 1, 'FAIL: order item insert';
END $$;

-- Duplicate receipt number must fail
DO $$ BEGIN
    BEGIN
        INSERT INTO orders (status, payment_method, subtotal_pence, total_pence, receipt_number)
        VALUES ('paid', 'cash', 149, 149, 'RCP-0001');
        ASSERT FALSE, 'FAIL: duplicate receipt number should be rejected';
    EXCEPTION WHEN unique_violation THEN
        NULL; -- expected
    END;
END $$;

-- Return linked to original order
INSERT INTO returns (original_order_id, reason, refund_total_pence)
VALUES (1, 'Item was damaged', 149);

INSERT INTO return_items (return_id, order_item_id, quantity_returned, refund_pence, return_to_stock)
VALUES (1, 1, 1, 149, TRUE);

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM returns WHERE original_order_id = 1) = 1, 'FAIL: return insert';
END $$;

-- -----------------------------------------------
-- V006: Staff
-- -----------------------------------------------

INSERT INTO staff (first_name, last_name, email, role)
VALUES ('Ahmed', 'Hassan', 'ahmed@store.com', 'store_manager');

INSERT INTO staff (first_name, last_name, email, role)
VALUES ('Sara', 'Jones', 'sara@store.com', 'cashier');

-- Clock in
INSERT INTO staff_clock_events (staff_id, event_type)
VALUES (2, 'clock_in');

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM staff) = 2, 'FAIL: staff insert';
    ASSERT (SELECT COUNT(*) FROM staff_clock_events WHERE staff_id = 2) = 1, 'FAIL: clock event';
END $$;

-- Duplicate email must fail
DO $$ BEGIN
    BEGIN
        INSERT INTO staff (first_name, last_name, email, role)
        VALUES ('Duplicate', 'Person', 'ahmed@store.com', 'cashier');
        ASSERT FALSE, 'FAIL: duplicate staff email should be rejected';
    EXCEPTION WHEN unique_violation THEN
        NULL; -- expected
    END;
END $$;

-- -----------------------------------------------
-- V007: Expenses
-- -----------------------------------------------

INSERT INTO expenses (category, description, amount_pence, recorded_by, expense_date)
VALUES ('utilities', 'Monthly electricity bill for the main store — paid to British Gas for August 2026', 25000, 1, '2026-08-01');

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM expenses) = 1, 'FAIL: expense insert';
END $$;

-- Short description must fail
DO $$ BEGIN
    BEGIN
        INSERT INTO expenses (category, description, amount_pence, recorded_by, expense_date)
        VALUES ('utilities', 'Too short', 25000, 1, '2026-08-01');
        ASSERT FALSE, 'FAIL: short expense description should be rejected';
    EXCEPTION WHEN check_violation THEN
        NULL; -- expected
    END;
END $$;

-- -----------------------------------------------
-- V008: Food Safety Logs
-- -----------------------------------------------

INSERT INTO food_safety_temperature_logs (unit_name, department_id, temperature_celsius, result, performed_by, checked_at)
VALUES ('Dairy Fridge 1', 4, 3.5, 'pass', 1, NOW());

INSERT INTO food_safety_temperature_logs (unit_name, department_id, temperature_celsius, result, corrective_action, performed_by, checked_at)
VALUES ('Frozen Unit 2', 5, -10.0, 'fail', 'Unit switched off and stock moved to backup freezer', 1, NOW());

INSERT INTO food_safety_cleaning_logs (area_name, department_id, result, performed_by, cleaned_at)
VALUES ('Deli Slicer', 3, 'completed', 1, NOW());

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM food_safety_temperature_logs) = 2, 'FAIL: temp log insert';
    ASSERT (SELECT COUNT(*) FROM food_safety_temperature_logs WHERE result = 'fail') = 1, 'FAIL: fail result';
    ASSERT (SELECT COUNT(*) FROM food_safety_cleaning_logs) = 1, 'FAIL: cleaning log insert';
END $$;

-- -----------------------------------------------
-- V009: Activity Log
-- -----------------------------------------------

INSERT INTO activity_log (actor_staff_id, actor_role, action, entity_type, entity_id, after_state)
VALUES (1, 'store_manager', 'order.create', 'order', '1', '{"total_pence": 149}'::jsonb);

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM activity_log) = 1, 'FAIL: activity log insert';
END $$;

-- UPDATE must be silently blocked (RULE does INSTEAD NOTHING)
UPDATE activity_log SET action = 'tampered' WHERE id = 1;

DO $$ BEGIN
    ASSERT (SELECT action FROM activity_log WHERE id = 1) = 'order.create', 'FAIL: activity log should be immutable to UPDATE';
END $$;

-- DELETE must be silently blocked
DELETE FROM activity_log WHERE id = 1;

DO $$ BEGIN
    ASSERT (SELECT COUNT(*) FROM activity_log) = 1, 'FAIL: activity log should be immutable to DELETE';
END $$;

-- -----------------------------------------------
-- All tests passed
-- -----------------------------------------------

DO $$ BEGIN
    RAISE NOTICE 'ALL TESTS PASSED';
END $$;

ROLLBACK;