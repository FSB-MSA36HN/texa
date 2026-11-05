import { runFixtureControl } from './fixture-control'

export default function globalTeardown() {
  runFixtureControl('restore')
}
