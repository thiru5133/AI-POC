/** A `tel:` link for a number, keeping only the digits and the leading +. */
export const telHref = (phone: string): string => `tel:${phone.replace(/[^+\d]/g, "")}`;
