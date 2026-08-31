export type UserRole = 'analyst' | 'approver' | 'admin';

export interface User {
  email: string;
  role: UserRole;
  full_name?: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  role: UserRole;
  email: string;
  user?: User;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface RegisterCredentials {
  fullname: string;
  email: string;
  password: string;
  role: UserRole;
}
