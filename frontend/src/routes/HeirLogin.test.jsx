// @vitest-environment jsdom
import React from 'react';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '@testing-library/jest-dom';
import HeirLoginPage from './HeirLogin';
import { useMediationStore } from '../store/useMediationStore';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: vi.fn(),
}));

describe('HeirLoginPage', () => {
  let heirPasswordLogin;

  beforeEach(() => {
    heirPasswordLogin = vi.fn().mockResolvedValue();
    useMediationStore.mockImplementation((selector) => selector({ heirPasswordLogin }));
    mockNavigate.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('submits heir credentials and navigates to dashboard', async () => {
    render(
      <MemoryRouter>
        <HeirLoginPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText(/Email or Display Name/i), {
      target: { value: 'heir@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/^Password$/i), {
      target: { value: 'heirpass123' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Sign In/i }));

    await waitFor(() => {
      expect(heirPasswordLogin).toHaveBeenCalledWith({
        identifier: 'heir@example.com',
        password: 'heirpass123',
      });
      expect(mockNavigate).toHaveBeenCalledWith('/dashboard');
    });
  });

  it('shows login errors', async () => {
    heirPasswordLogin.mockRejectedValueOnce(new Error('Invalid credentials'));

    render(
      <MemoryRouter>
        <HeirLoginPage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByLabelText(/Email or Display Name/i), {
      target: { value: 'heir@example.com' },
    });
    fireEvent.change(screen.getByLabelText(/^Password$/i), {
      target: { value: 'wrongpass' },
    });
    fireEvent.click(screen.getByRole('button', { name: /Sign In/i }));

    expect(await screen.findByText('Invalid credentials')).toBeInTheDocument();
  });
});
