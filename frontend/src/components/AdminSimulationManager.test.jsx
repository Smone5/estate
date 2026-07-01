// @vitest-environment jsdom
import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import '@testing-library/jest-dom';
import AdminSimulationManager from './AdminSimulationManager';
import { DEFAULT_SIMULATION_CONFIG } from '../utils/simulationConfig';

vi.mock('../store/useMediationStore', () => ({
  useMediationStore: (selector) => selector({ loadSessionDetails: vi.fn() }),
}));

describe('AdminSimulationManager registered-heir workflow', () => {
  beforeEach(() => {
    global.fetch = vi.fn((url) => {
      if (String(url).endsWith('/simulation/config')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            config: DEFAULT_SIMULATION_CONFIG,
            published: true,
            required_for_launch: true,
          }),
        });
      }
      return Promise.resolve({
        ok: true,
        json: async () => ({
          published: true,
          required_for_launch: true,
          total_heirs: 2,
          completed_heirs: 1,
          heirs: [
            { heir_id: '1', display_name: 'Alex', status: 'PENDING', practice_completed_at: null },
            { heir_id: '2', display_name: 'Jordan', status: 'ACTIVE', practice_completed_at: '2026-07-01T12:00:00Z' },
          ],
        }),
      });
    });
  });

  it('shows session practice progress for registered heirs', async () => {
    render(
      <MemoryRouter>
        <AdminSimulationManager sessionId="session-1" />
      </MemoryRouter>,
    );

    expect(await screen.findByText('1 of 2 complete')).toBeInTheDocument();
    expect(screen.getByText('Alex')).toBeInTheDocument();
    expect(screen.getByText('Not completed')).toBeInTheDocument();
    expect(screen.getAllByText('Jordan').length).toBeGreaterThan(0);
    expect(screen.getByText('Practice complete')).toBeInTheDocument();
  });
});
