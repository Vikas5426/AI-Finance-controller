import api from './api';
import { LoginCredentials, RegisterCredentials, TokenResponse, User } from '../types/auth';

export const authService = {
  login: async (credentials: LoginCredentials): Promise<TokenResponse> => {
    const res = await api.post<TokenResponse>('/auth/login', credentials);
    if (res.data.access_token) {
      localStorage.setItem('fin_jwt_token', res.data.access_token);
      const profile: User = {
        email: res.data.email,
        role: res.data.role,
        full_name: res.data.user?.full_name || res.data.email.split('@')[0],
      };
      localStorage.setItem('fin_user_profile', JSON.stringify(profile));
    }
    return res.data;
  },

  register: async (credentials: RegisterCredentials): Promise<TokenResponse> => {
    const res = await api.post<TokenResponse>('/auth/register', credentials);
    if (res.data.access_token) {
      localStorage.setItem('fin_jwt_token', res.data.access_token);
      const profile: User = {
        email: res.data.email,
        role: res.data.role,
        full_name: credentials.fullname,
      };
      localStorage.setItem('fin_user_profile', JSON.stringify(profile));
    }
    return res.data;
  },

  logout: () => {
    localStorage.removeItem('fin_jwt_token');
    localStorage.removeItem('fin_user_profile');
    window.location.reload();
  },

  getCurrentUser: (): User | null => {
    const profile = localStorage.getItem('fin_user_profile');
    if (!profile) return null;
    try {
      return JSON.parse(profile);
    } catch {
      return null;
    }
  },

  getToken: (): string | null => {
    return localStorage.getItem('fin_jwt_token');
  },
};
