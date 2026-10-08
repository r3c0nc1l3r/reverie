// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// Served as a GitHub Pages project site: https://r3c0nc1l3r.github.io/reverie/
export default defineConfig({
	site: 'https://r3c0nc1l3r.github.io',
	base: '/reverie',
	trailingSlash: 'ignore',
	integrations: [
		starlight({
			title: 'Reverie',
			description:
				'Spec-driven browser tests: local Laya clicks, a multimodal pilot, and an orchestrator CLI.',
			logo: { src: './src/assets/logo.svg' },
			favicon: '/favicon.svg',
			social: [{ icon: 'github', label: 'GitHub', href: 'https://github.com/r3c0nc1l3r/reverie' }],
			editLink: { baseUrl: 'https://github.com/r3c0nc1l3r/reverie/edit/main/website/' },
			lastUpdated: false,
			customCss: ['./src/styles/custom.css'],
			sidebar: [
				{
					label: 'Start here',
					items: [
						{ label: 'Overview', link: '/' },
						{ slug: 'start/concepts' },
						{ slug: 'start/installation' },
						{ slug: 'start/first-run' },
					],
				},
				{
					label: 'Guides',
					items: [
						{ slug: 'guides/writing-specs' },
						{ slug: 'guides/running-specs' },
						{ slug: 'guides/runs-and-dashboard' },
						{ slug: 'guides/docker' },
						{ slug: 'guides/narration' },
						{ slug: 'guides/examples' },
						{ slug: 'guides/fieldops-demo' },
						{ slug: 'guides/widgetlab-demo' },
						{ slug: 'guides/agent-skills' },
					],
				},
				{
					label: 'Reference',
					items: [
						{ slug: 'reference/cli' },
						{ slug: 'reference/configuration' },
						{ slug: 'reference/models' },
					],
				},
				{
					label: 'Help',
					items: [{ slug: 'help/troubleshooting' }],
				},
				{
					label: 'Project',
					items: [{ slug: 'project/changelog' }, { slug: 'project/contributing' }],
				},
			],
		}),
	],
});
