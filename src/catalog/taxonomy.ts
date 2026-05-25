export type CategorySeed = {
  code: string;
  label: string;
  description: string;
  layout_type?: string;
  requires_slots?: boolean;
  requires_temperature_control?: boolean;
  requires_recipes?: boolean;
  requires_freezer?: boolean;
  requires_heating?: boolean;
  metadata?: Record<string, unknown>;
};

export const categorySeeds: CategorySeed[] = [
  {
    code: 'coffee',
    label: 'Cafe',
    description: 'Maquinas de cafe, espresso automatico, bean-to-cup y bebidas calientes.',
    layout_type: 'ingredient_modules',
    requires_recipes: true,
    metadata: { compatible_modules: ['recipes', 'ingredients', 'cups', 'cleaning_cycles', 'cashless_payment'] }
  },
  {
    code: 'snack_drink',
    label: 'Snacks y bebidas',
    description: 'Maquinas de espirales, bandejas, bebidas frias, snacks secos o combos.',
    layout_type: 'spiral_slots',
    requires_slots: true,
    requires_temperature_control: true,
    metadata: { compatible_modules: ['planogram', 'slot_replenishment', 'stock', 'temperature'] }
  },
  {
    code: 'cold_beverage',
    label: 'Bebidas frias',
    description: 'Maquinas refrigeradas de latas, botellas y bebidas.',
    layout_type: 'columns_or_trays',
    requires_slots: true,
    requires_temperature_control: true
  },
  {
    code: 'ice_cream',
    label: 'Helados / congelados',
    description: 'Maquinas de helados, frozen food o productos congelados.',
    layout_type: 'frozen_trays_or_robotic',
    requires_temperature_control: true,
    requires_freezer: true,
    metadata: { compatible_modules: ['temperature', 'frozen_inventory', 'robotic_pickup_optional'] }
  },
  {
    code: 'hot_food',
    label: 'Comida caliente',
    description: 'Maquinas que mantienen o calientan alimentos.',
    layout_type: 'heated_compartments',
    requires_temperature_control: true,
    requires_heating: true
  },
  {
    code: 'fresh_food',
    label: 'Fresh food',
    description: 'Maquinas para ensaladas, frutas, sandwiches y alimentos refrigerados.',
    layout_type: 'refrigerated_compartments',
    requires_temperature_control: true,
    metadata: { requires_expiration_control: true }
  },
  {
    code: 'smart_locker',
    label: 'Locker inteligente',
    description: 'Lockers o casilleros inteligentes para retiro, venta o entrega.',
    layout_type: 'locker_doors',
    metadata: { requires_door_control: true }
  },
  {
    code: 'ice_water',
    label: 'Hielo / agua',
    description: 'Maquinas de despacho de hielo, agua o ambos.',
    layout_type: 'bulk_dispensing',
    metadata: { requires_water_or_ice_module: true }
  },
  {
    code: 'industrial',
    label: 'Industrial / EPP',
    description: 'Maquinas para herramientas, EPP, repuestos o insumos industriales.',
    layout_type: 'industrial_slots_or_lockers',
    metadata: { requires_audit_control: true }
  },
  {
    code: 'other',
    label: 'Otros',
    description: 'Tipo no clasificado o pendiente de revision.'
  }
];

export const categoryKeywords: Record<string, string[]> = {
  coffee: ['coffee', 'espresso', 'bean-to-cup', 'cafe', 'hot drinks', 'fresh milk', 'instant'],
  snack_drink: ['snack', 'drink', 'combo', 'spiral', 'glass front', 'cold & snack'],
  cold_beverage: ['beverage', 'bottle', 'can', 'cold drink', 'refrigerated'],
  ice_cream: ['ice cream', 'frozen', 'freezer', 'gelato', 'frozen food'],
  hot_food: ['hot food', 'heated', 'microwave', 'pizza', 'warm'],
  fresh_food: ['fresh food', 'salad', 'sandwich', 'fruit', 'vegetable'],
  smart_locker: ['locker', 'pickup', 'smart locker', 'compartment'],
  ice_water: ['ice', 'water', 'bagged ice', 'water vending'],
  industrial: ['industrial', 'ppe', 'tools', 'mro', 'inventory control']
};

export const manufacturerSeeds = [
  'Crane / CPI',
  'Evoca Group / Necta',
  'Azkoyen / Coffetek',
  'Fuji Electric',
  'SandenVendo',
  'FAS International',
  'Bianchi Vending',
  'Jofemar',
  'Sielaff',
  'AMS Vendors',
  'Seaga',
  'Royal Vendors',
  'U-Select-It / USI',
  'Westomatic',
  'Rhea Vendors',
  'Fastcorp',
  'TCN Vending',
  'Vendlife',
  'XY Vending',
  'WMF Professional Coffee Machines',
  'Schaerer',
  'Eversys',
  'Bravilor Bonamat',
  'BUNN',
  'Saeco Professional',
  'Huaxin Vending',
  'SweetRobo',
  'ColdSnap',
  'Kooler Ice'
];
