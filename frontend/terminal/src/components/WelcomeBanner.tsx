import React, {useEffect, useState} from 'react';
import {Box, Text} from 'ink';

import {useTheme} from '../theme/ThemeContext.js';

const VERSION = '0.1.0';

// AutoModeIndicator: animated orange "AUTO" badge shown when permission_mode=full_auto.
export function AutoModeIndicator(): React.JSX.Element {
	const [visible, setVisible] = useState(true);

	useEffect(() => {
		const id = setInterval(() => setVisible((v) => !v), 600);
		return () => clearInterval(id);
	}, []);

	if (!visible) {
		return (
			<Box>
				<Text> </Text>
			</Box>
		);
	}

	return (
		<Box>
			<Text color="yellow" bold dimColor>
				{' '}
				[ AUTO ]{' '}
			</Text>
		</Box>
	);
}

// prettier-ignore
const LOGO = [
	' ██████╗ ██╗  ██╗    ███╗   ███╗██╗   ██╗    ██╗  ██╗ █████╗ ██████╗ ███╗   ██╗███████╗███████╗███████╗██╗',
	'██╔═══██╗██║  ██║    ████╗ ████║╚██╗ ██╔╝    ██║  ██║██╔══██╗██╔══██╗████╗  ██║██╔════╝██╔════╝██╔════╝██║',
	'██║   ██║███████║    ██╔████╔██║ ╚████╔╝     ███████║███████║██████╔╝██╔██╗ ██║█████╗  ███████╗███████╗██║',
	'██║   ██║██╔══██║    ██║╚██╔╝██║  ╚██╔╝      ██╔══██║██╔══██║██╔══██╗██║╚██╗██║██╔══╝  ╚════██║╚════██║╚═╝',
	'╚██████╔╝██║  ██║    ██║ ╚═╝ ██║   ██║       ██║  ██║██║  ██║██║  ██║██║ ╚████║███████╗███████║███████║██╗',
	' ╚═════╝ ╚═╝  ╚═╝    ╚═╝     ╚═╝   ╚═╝       ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝╚══════╝╚══════╝╚══════╝╚═╝',
];

export function WelcomeBanner(): React.JSX.Element {
	const {theme} = useTheme();

	return (
		<Box flexDirection="column" marginBottom={1}>
			<Box flexDirection="column" paddingX={0}>
				{LOGO.map((line, i) => (
					<Text key={i} color={theme.colors.primary} bold>{line}</Text>
				))}
				<Text> </Text>
				<Text>
					<Text dimColor> An AI-powered coding assistant</Text>
					<Text dimColor>{'  '}v{VERSION}</Text>
				</Text>
				<Text> </Text>
				<Text>
					<Text dimColor> </Text>
					<Text color={theme.colors.primary}>/help</Text>
					<Text dimColor> commands</Text>
					<Text dimColor>{'  '}|{'  '}</Text>
					<Text color={theme.colors.primary}>/model</Text>
					<Text dimColor> switch</Text>
					<Text dimColor>{'  '}|{'  '}</Text>
					<Text color={theme.colors.primary}>Ctrl+C</Text>
					<Text dimColor> exit</Text>
				</Text>
			</Box>
		</Box>
	);
}
