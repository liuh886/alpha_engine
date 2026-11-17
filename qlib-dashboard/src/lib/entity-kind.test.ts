import { describe, expect, it } from 'vitest';
import { ENTITY_KIND_LABEL, entityKindFromRoles, formatEntityRoles } from './entity-kind';

describe('entityKindFromRoles', () => {
  it('keeps a selected-pool candidate an instrument', () => {
    expect(entityKindFromRoles(['selected_pool_candidate'])).toBe('instrument');
    expect(entityKindFromRoles(['selected_pool_candidate', 'formal_traded'])).toBe('instrument');
  });

  it('classifies the governed benchmark role as the market index identity', () => {
    expect(entityKindFromRoles(['benchmark'])).toBe('index');
    expect(entityKindFromRoles(['benchmark', 'formal_traded'])).toBe('index');
  });

  it('classifies governed auxiliary and comparison roles as references', () => {
    expect(entityKindFromRoles(['formal_auxiliary'])).toBe('reference');
    expect(entityKindFromRoles(['comparison_reference'])).toBe('reference');
  });

  it('never invents an index or reference from an empty or unknown role list', () => {
    expect(entityKindFromRoles([])).toBe('instrument');
    expect(entityKindFromRoles(undefined)).toBe('instrument');
    expect(entityKindFromRoles(['something_new'])).toBe('instrument');
  });

  it('gives benchmark priority when several governed context roles appear', () => {
    expect(entityKindFromRoles(['formal_auxiliary', 'benchmark'])).toBe('index');
  });
});

describe('formatEntityRoles', () => {
  it('renders the catalog roles in order with their governed labels', () => {
    expect(formatEntityRoles(['benchmark', 'formal_traded'])).toBe('Market benchmark · Formal traded');
    expect(formatEntityRoles(['selection_pool_candidate', 'selected_pool_candidate'])).toBe('Selected pool candidate');
  });

  it('falls back to a plain governed instrument without inventing a role', () => {
    expect(formatEntityRoles([])).toBe('Governed instrument');
    expect(formatEntityRoles(['unknown_role'])).toBe('Governed instrument');
  });

  it('labels the four entity kinds unambiguously', () => {
    expect(ENTITY_KIND_LABEL).toEqual({
      model: 'Model',
      instrument: 'Instrument',
      index: 'Index',
      reference: 'Reference',
    });
  });
});
