export function isMainAdminUser(user) {
  if (!user) return false;
  return user.role === "admin" || !!user.is_main_admin;
}

export function isSecondaryAdminUser(user) {
  if (!user) return false;
  return user.role === "secondary_admin" || !!user.is_secondary_admin;
}
