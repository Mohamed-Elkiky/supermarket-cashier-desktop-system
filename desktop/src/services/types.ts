/** Shared domain types for the renderer (mirrors the Django REST API shapes). */

export interface AuthTokens {
  access: string;
  refresh: string;
  email: string;
  role: string;
}

export interface Category {
  id: number;
  name: string;
}

export interface Department {
  id: number;
  name: string;
  categories?: Category[];
}

export interface AllergenLink {
  allergen: { name: string; eu_code: string };
  may_contain: boolean;
}

export type PricingMode = "fixed" | "weight_based";

export interface ProductVariant {
  id: number;
  product: number;
  sku: string;
  barcode: string | null;
  name: string;
  pricing_mode: PricingMode;
  sell_price: number; // integer pence
  cost_price?: number;
  unit_of_measure: string;
  allergens: AllergenLink[];
  margin_percent?: string;
  low_stock_threshold?: number;
  line_total_example?: string;
}

export interface Product {
  id: number;
  name: string;
  department: number;
  is_age_restricted?: boolean;
  age_restriction_years?: number | null;
  variants: ProductVariant[];
}

export interface OrderItem {
  id: number;
  variant: number;
  variant_name_snapshot: string;
  unit_price_display: string;
  weight_kg: number | null;
  quantity: number;
  promotion_name: string | null;
  discount_display: string | null;
  line_total_display: string;
}

export interface Order {
  id: number;
  status: string;
  items: OrderItem[];
  subtotal_pence?: number;
  discount_total_pence?: number;
  tax_total_pence?: number;
  total_pence?: number;
  subtotal_display?: string;
  discount_total_display?: string;
  tax_total_display?: string;
  total_display?: string;
  receipt_number?: string;
  change_given_pence?: number;
  loyalty_points_earned?: number;
}

export interface Customer {
  id: number;
  name?: string;
  full_name?: string;
  email?: string;
  loyalty_points?: number;
}

export interface ExpiryInfo {
  has_expired_stock: boolean;
  batches?: Array<{ best_before_date?: string; use_by_date?: string }>;
}

export interface LineTotalResult {
  line_total_display: string;
  line_total_pence?: number;
}

export interface StockRow {
  variant_id: number;
  sku: string;
  name: string;
  stock_quantity: number;
  unit_of_measure: string;
  low_stock_threshold: number;
  is_low_stock: boolean;
}

export interface LedgerMovementPayload {
  variant_id: number;
  department_id: number;
  movement_type: string;
  quantity: number;
  reason: string;
}

export type PaymentMethod = "cash" | "card";

export interface CheckoutPayload {
  payment_method: PaymentMethod;
  cash_tendered_pence?: number;
  age_verified: boolean;
  age_verification_id_type?: string;
  customer_id?: number;
}
