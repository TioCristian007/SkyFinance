export const BANKS = {
  bchile:      { name: 'Banco de Chile', color: '#001C4B', logo: '/assets/banks/banco-chile.png', shortCode: 'BCH' },
  bci:         { name: 'BCI',             color: '#FFD100', logo: '/assets/banks/bci.png',         shortCode: 'BCI' },
  bancoestado: { name: 'BancoEstado',     color: '#003C71', logo: '/assets/banks/bancoestado.png', shortCode: 'BE'  },
  santander:   { name: 'Santander',       color: '#EC0000', logo: '/assets/banks/santander.png',   shortCode: 'SAN' },
  falabella:   { name: 'Falabella',       color: '#1E8449', logo: '/assets/banks/falabella.png',   shortCode: 'FAL' },
};

export const DEFAULT_BANK = { name: 'Otro', color: '#94A3B8', logo: null, shortCode: '—' };

export function getBankMeta(bankId) {
  if (!bankId) return DEFAULT_BANK;
  const key = String(bankId).toLowerCase().trim();
  if (BANKS[key]) return BANKS[key];
  const match = Object.values(BANKS).find(b =>
    b.name.toLowerCase() === key || b.shortCode.toLowerCase() === key
  );
  return match ?? DEFAULT_BANK;
}
