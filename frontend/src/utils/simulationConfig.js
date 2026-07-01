export const SIMULATION_IMAGE_OPTIONS = [
  { value: '/simulation/mantel-clock.webp', label: 'Walnut mantel clock' },
  { value: '/simulation/recipe-box.webp', label: 'Recipe box' },
  { value: '/simulation/film-camera.webp', label: 'Film camera' },
  { value: '/simulation/pearl-necklace.webp', label: 'Pearl necklace' },
  { value: '/simulation/rocking-chair.webp', label: 'Rocking chair' },
  { value: '/simulation/harbor-watercolor.webp', label: 'Harbor watercolor' },
];

export const DEFAULT_SIMULATION_CONFIG = {
  version: 1,
  required_for_launch: true,
  title: 'The Hartwell Family Practice Estate',
  welcome_message:
    'This fictional household lets you rehearse the complete allocation process before your family session begins.',
  items: [
    {
      id: 'mantel-clock',
      title: 'Walnut Mantel Clock',
      category: 'Furniture',
      description: 'A 1940s walnut clock that sat above the family-room fireplace.',
      story: 'The clock was wound every Sunday evening before supper.',
      value_range: '$180–$320',
      image: '/simulation/mantel-clock.webp',
      enabled: true,
      companion_points: { jordan: 260, casey: 80 },
    },
    {
      id: 'recipe-box',
      title: 'Handwritten Recipe Box',
      category: 'Family History',
      description: 'An oak box containing several decades of handwritten recipe cards.',
      story: 'Many cards include notes added after large family meals.',
      value_range: '$30–$60',
      image: '/simulation/recipe-box.webp',
      enabled: true,
      companion_points: { jordan: 80, casey: 430 },
    },
    {
      id: 'film-camera',
      title: '35mm Family Camera',
      category: 'Collectibles',
      description: 'A well-used 1960s film camera with its original leather strap.',
      story: 'Most childhood vacation photographs were taken with this camera.',
      value_range: '$120–$220',
      image: '/simulation/film-camera.webp',
      enabled: true,
      companion_points: { jordan: 340, casey: 110 },
    },
    {
      id: 'pearl-necklace',
      title: 'Pearl Necklace',
      category: 'Jewelry',
      description: 'A single strand of cream pearls with a small vintage silver clasp.',
      story: 'It was worn for anniversaries, graduations, and family weddings.',
      value_range: '$250–$450',
      image: '/simulation/pearl-necklace.webp',
      enabled: true,
      companion_points: { jordan: 60, casey: 250 },
    },
    {
      id: 'rocking-chair',
      title: 'Oak Rocking Chair',
      category: 'Furniture',
      description: 'A handmade oak rocker with a woven cane seat and visible patina.',
      story: 'Three generations of children were rocked to sleep in this chair.',
      value_range: '$140–$260',
      image: '/simulation/rocking-chair.webp',
      enabled: true,
      companion_points: { jordan: 180, casey: 90 },
    },
    {
      id: 'harbor-watercolor',
      title: 'Harbor Watercolor',
      category: 'Art',
      description: 'A modest original watercolor of a New England harbor in an oak frame.',
      story: 'Painted during the family’s first summer by the coast.',
      value_range: '$75–$150',
      image: '/simulation/harbor-watercolor.webp',
      enabled: true,
      companion_points: { jordan: 80, casey: 40 },
    },
  ],
};

export function cloneSimulationConfig(config = DEFAULT_SIMULATION_CONFIG) {
  return JSON.parse(JSON.stringify(config));
}

export async function loadSimulationConfig() {
  try {
    const response = await fetch('/api/simulation/config');
    if (!response.ok) throw new Error('Practice configuration is unavailable.');
    return await response.json();
  } catch {
    return cloneSimulationConfig();
  }
}

export async function loadSessionSimulationContext(sessionId) {
  if (!sessionId) {
    return {
      config: await loadSimulationConfig(),
      registered: false,
      published: true,
      required_for_launch: false,
      completed_at: null,
    };
  }
  const response = await fetch(`/api/sessions/${sessionId}/simulation/config`, {
    credentials: 'same-origin',
  });
  if (!response.ok) throw new Error('Session practice configuration is unavailable.');
  return response.json();
}

export async function loadHeirSimulationContext() {
  try {
    const response = await fetch('/api/heirs/me/simulation', { credentials: 'same-origin' });
    if (response.ok) return response.json();
  } catch {
    // Fall through to the no-account guest rehearsal.
  }
  return {
    config: await loadSimulationConfig(),
    registered: false,
    published: true,
    required_for_launch: false,
    completed_at: null,
  };
}
