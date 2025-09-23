import streamlit as st
import pandas as pd
import numpy as np
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import inch
import io
from io import StringIO
from datetime import datetime

# Set page config
st.set_page_config(
    page_title="Sales Order Pick List Generator",
    page_icon="📦",
    layout="wide"
)

st.title("📦 Sales Order Pick List Generator")
st.markdown("Generate custom pick lists from your sales order and assembly data with input package tracking")

# Initialize session state
if 'processed_data' not in st.session_state:
    st.session_state.processed_data = None
if 'so_data' not in st.session_state:
    st.session_state.so_data = None
if 'assembly_data' not in st.session_state:
    st.session_state.assembly_data = None
if 'product_data' not in st.session_state:
    st.session_state.product_data = None

# Function to clean and load CSV data
def load_csv_with_metadata_skip(uploaded_file):
    """
    Load CSV file and skip metadata lines at the top
    """
    try:
        # Read the raw content
        content = uploaded_file.getvalue().decode('utf-8')
        lines = content.split('\n')
        
        # Skip the first 3 lines (metadata) and rejoin
        csv_content = '\n'.join(lines[3:])
        
        # Use StringIO to create a file-like object for pandas
        from io import StringIO
        csv_file = StringIO(csv_content)
        
        # Read with pandas
        df = pd.read_csv(csv_file)
        return df
        
    except Exception as e:
        st.error(f"Error loading CSV: {str(e)}")
        return None

# Function to process the data (replicating your Google Sheets formula)
def process_data(so_df, assembly_df, product_df=None):
    """
    Replicates the Google Sheets QUERY formula logic based on actual CSV structure
    """
    try:
        # Extract relevant columns from Sales Orders using actual column names
        so_columns = {
            'Customer': so_df['Customer'],
            'Order_Number': so_df['Order Number'],  # Keep internal name as Order_Number for consistency
            'Category': so_df['Category'],
            'Product': so_df['Product'],
            'Product_ID': so_df['Product Id'],  # Corrected column name
            'Batch_Number': so_df['Package Batch Number'],
            'Lookup_Value': so_df['Package Label'],  # This is what we lookup in Assembly
            'Quantity': so_df['Quantity']
        }
        
        # Create base dataframe
        result_df = pd.DataFrame(so_columns)
        
        # Assembly data processing (replicating your VLOOKUP logic)
        # Filter assembly data where Input/Output = "Output"
        assembly_output = assembly_df[assembly_df['Input/Output'] == "Output"]
        assembly_input = assembly_df[assembly_df['Input/Output'] == "Input"]
        
        # Create lookup dictionaries for the nested lookup
        # First lookup: Package Label -> Assembly Number (from Output records)
        package_to_assembly = dict(zip(assembly_output['Package Number'], assembly_output['Assembly Number']))
        
        # Second lookup: Assembly Number -> Package Number (from Input records)  
        assembly_to_input_package = dict(zip(assembly_input['Assembly Number'], assembly_input['Package Number']))
        
        # Perform the nested lookup (replicating your VLOOKUP formula)
        input_package_numbers = []
        for lookup_val in result_df['Lookup_Value']:
            try:
                # First lookup: find Assembly Number from Package Label where Input/Output="Output"
                assembly_number = package_to_assembly.get(lookup_val, None)
                # Second lookup: find Package Number from Assembly Number where Input/Output="Input"
                input_package = assembly_to_input_package.get(assembly_number, "") if assembly_number else ""
                input_package_numbers.append(input_package)
            except:
                input_package_numbers.append("")
        
        result_df['Input_Package_Number'] = input_package_numbers
        
        # Product data processing - calculate number of cases (Quantity ÷ Units Per Case)
        cases = []
        if product_df is not None:
            # Create lookup dictionary: Product ID -> Units Per Case
            product_lookup = dict(zip(product_df['ID'], product_df['Units Per Case']))
            
            for idx, row in result_df.iterrows():
                product_id = row['Product_ID']
                quantity = row['Quantity']
                
                try:
                    units_per_case = product_lookup.get(product_id, None)
                    
                    # Calculate cases if we have valid data
                    if (pd.notna(units_per_case) and units_per_case != '' and 
                        pd.notna(quantity) and quantity != '' and 
                        float(units_per_case) > 0):
                        
                        calculated_cases = float(quantity) / float(units_per_case)
                        # Round to 2 decimal places for display
                        cases.append(round(calculated_cases, 2))
                    else:
                        cases.append("")
                except:
                    cases.append("")
        else:
            # No product data available
            cases = [""] * len(result_df)
        
        result_df['Cases'] = cases
        
        # Remove the Lookup_Value and Product_ID columns as they're not needed in the final output
        result_df = result_df.drop(['Lookup_Value', 'Product_ID'], axis=1)
        
        # Reorder columns with Cases as second to last (after Quantity, before Picked will be added in PDF)
        columns_order = ['Customer', 'Order_Number', 'Category', 'Product', 'Batch_Number', 'Input_Package_Number', 'Quantity', 'Cases']
        result_df = result_df[columns_order]
        
        # Filter out null customers and sort (replicating your QUERY)
        result_df = result_df[result_df['Customer'].notna() & (result_df['Customer'] != "")]
        result_df = result_df.sort_values(['Customer', 'Order_Number', 'Category', 'Product'])  # Order_Number internally, displays as Sales Order
        
        # Reset index
        result_df = result_df.reset_index(drop=True)
        
        return result_df
        
    except Exception as e:
        st.error(f"Error processing data: {str(e)}")
        st.info("Please check that your CSV files have the expected column structure.")
        st.info(f"Available Sales Order columns: {list(so_df.columns)}")
        st.info(f"Available Assembly columns: {list(assembly_df.columns)}")
        if product_df is not None:
            st.info(f"Available Product columns: {list(product_df.columns)}")
        return None

# Function to generate PDF
def generate_pdf(df, selected_filters=None, hide_customer=False, hide_sales_order=False, portrait_mode=False):
    """
    Generate a styled PDF report with landscape or portrait orientation and custom color scheme
    """
    buffer = io.BytesIO()
    
    # Choose orientation based on user preference
    from reportlab.lib.pagesizes import A4, landscape
    if portrait_mode:
        page_size = A4
        doc = SimpleDocTemplate(buffer, pagesize=A4, 
                              topMargin=0.5*inch, bottomMargin=0.5*inch,
                              leftMargin=0.3*inch, rightMargin=0.3*inch)
    else:
        page_size = landscape(A4)
        doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), 
                              topMargin=0.5*inch, bottomMargin=0.5*inch,
                              leftMargin=0.3*inch, rightMargin=0.3*inch)
    
    # Get styles
    styles = getSampleStyleSheet()
    filter_style = ParagraphStyle(
        'FilterStyle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.Color(0.4, 0.4, 0.4),  # Same as other text
        alignment=1,  # Center alignment
        spaceAfter=10
    )
    
    elements = []
    
    # Add filter information in header if any
    if selected_filters:
        filter_values = []
        for key, value in selected_filters.items():
            if value:
                # Just show the values, not the labels
                if isinstance(value, list):
                    filter_values.extend(value)
                else:
                    filter_values.append(value)
        
        if filter_values:
            filter_text = " | ".join(filter_values)
            filter_para = Paragraph(filter_text, filter_style)
            elements.append(filter_para)
    
    # Extract unique customers and sales orders for footer (regardless of column visibility)
    unique_customers = sorted(df['Customer'].unique())
    unique_sales_orders = sorted(df['Order_Number'].unique())
    
    # Function to wrap text for display with smart width detection
    def wrap_text_smart(text, column_width_inches, font_size=8):
        """Smart text wrapping based on actual column width"""
        if not text or pd.isna(text):
            return ""
        
        text = str(text).strip()
        if not text:
            return ""
        
        # More accurate character estimation for Helvetica font
        # Average character width in Helvetica is roughly 0.5-0.6 * font_size
        points_width = column_width_inches * 72 - 12  # Subtract padding (6 points each side)
        avg_char_width = 0.55 * font_size  # More conservative estimate
        max_chars_per_line = int(points_width / avg_char_width)
        
        # Don't wrap if text fits comfortably
        if len(text) <= max_chars_per_line:
            return text
        
        # Find the best break point after a hyphen
        best_break = None
        
        # Look for hyphens within reasonable range, break AFTER the hyphen
        for i in range(max_chars_per_line, max(max_chars_per_line//3, 5), -1):
            if i < len(text) and text[i-1] == '-':
                best_break = i  # This puts hyphen at end of first line
                break
        
        # If no hyphen found, look for spaces
        if not best_break:
            for i in range(max_chars_per_line, max(max_chars_per_line//3, 5), -1):
                if i < len(text) and text[i-1] == ' ':
                    best_break = i - 1  # Break before the space
                    break
        
        # If still no good break point, don't wrap (let it overflow slightly rather than bad break)
        if not best_break or best_break < max_chars_per_line//3:
            return text
        
        return text[:best_break] + '\n' + text[best_break:].strip()
    
    # Function to wrap text for display (for fixed-width columns)
    def wrap_text(text, max_length=20, break_chars=None):
        """Simple text wrapping function for columns with known limits"""
        if not text or len(str(text)) <= max_length:
            return str(text)
        
        text = str(text)
        
        # Find break points, prioritizing hyphens
        for i in range(max_length, max(max_length//2, 1), -1):
            if i < len(text):
                if text[i-1] == '-':
                    return text[:i] + '\n' + text[i:].strip()
                elif text[i-1] == ' ':
                    return text[:i-1] + '\n' + text[i:].strip()
        
        # No good break point found, break at max_length
        return text[:max_length] + '\n' + text[max_length:]
    
    # Function to get last 14 characters of package number
    def truncate_package_number(package_text):
        if not package_text or len(str(package_text)) <= 14:
            return str(package_text)
        return str(package_text)[-14:]
    
    # Build headers and column widths based on visibility options and orientation
    headers = []
    col_widths = []
    
    if not hide_customer:
        headers.append('Customer')
        col_widths.append(1.3*inch if not portrait_mode else 1*inch)
    
    if not hide_sales_order:
        headers.append('SO')
        col_widths.append(1*inch if not portrait_mode else 0.8*inch)
    
    # Always include these columns
    headers.extend(['Category', 'Product', 'Batch', 'Package', 'Qty', 'Cases', 'Picked'])
    
    # Adjust column widths based on hidden columns and orientation
    if portrait_mode:
        # Portrait mode - tighter spacing
        if hide_customer and hide_sales_order:
            col_widths.extend([0.8*inch, 2.5*inch, 0.9*inch, 0.9*inch, 0.5*inch, 0.5*inch, 0.6*inch])
        elif hide_customer or hide_sales_order:
            col_widths.extend([0.7*inch, 2.1*inch, 0.8*inch, 0.8*inch, 0.5*inch, 0.5*inch, 0.6*inch])
        else:
            col_widths.extend([0.6*inch, 1.8*inch, 0.7*inch, 0.7*inch, 0.4*inch, 0.4*inch, 0.5*inch])
    else:
        # Landscape mode - existing widths
        if hide_customer and hide_sales_order:
            col_widths.extend([1.1*inch, 3.8*inch, 1.3*inch, 1.3*inch, 0.7*inch, 0.7*inch, 0.9*inch])
        elif hide_customer or hide_sales_order:
            col_widths.extend([1*inch, 3.2*inch, 1.2*inch, 1.2*inch, 0.6*inch, 0.6*inch, 0.8*inch])
        else:
            col_widths.extend([0.9*inch, 2.5*inch, 1.1*inch, 1.1*inch, 0.6*inch, 0.6*inch, 0.8*inch])
    
    # Prepare table data
    table_data = [headers]
    
    for _, row in df.iterrows():
        # Handle None/NaN values for batch number
        batch_number = str(row['Batch_Number']) if pd.notna(row['Batch_Number']) and str(row['Batch_Number']).lower() != 'none' else ""
        
        # Determine product column width based on visibility settings and orientation
        if portrait_mode:
            if hide_customer and hide_sales_order:
                product_width = 2.5
            elif hide_customer or hide_sales_order:
                product_width = 2.1
            else:
                product_width = 1.8
        else:
            if hide_customer and hide_sales_order:
                product_width = 3.8
            elif hide_customer or hide_sales_order:
                product_width = 3.2
            else:
                product_width = 2.5
        
        # Process text fields with smart wrapping for product names
        product_name = wrap_text_smart(str(row['Product']), product_width, font_size=8)
        category_wrapped = wrap_text(str(row['Category']), 12)  # Category still uses simple wrap
        batch_display = wrap_text(batch_number, 15) if batch_number else ""  # Remove third parameter
        package_display = truncate_package_number(row['Input_Package_Number']) if pd.notna(row['Input_Package_Number']) else ""
        
        # Handle Cases with wrapping
        cases_display = wrap_text(str(row['Cases']), 8) if pd.notna(row['Cases']) and str(row['Cases']) != "" else ""
        
        # Build row data based on visibility options
        row_data = []
        
        if not hide_customer:
            row_data.append(str(row['Customer']))
        
        if not hide_sales_order:
            row_data.append(str(row['Order_Number']))
        
        # Always include these columns
        row_data.extend([
            category_wrapped,
            product_name,  # Now using smart wrapping
            batch_display,
            package_display,
            str(row['Quantity']),
            cases_display,
            ""  # Empty Picked column for manual entry
        ])
        
        table_data.append(row_data)
    
    # Create table without header repetition
    table = Table(table_data, colWidths=col_widths, rowHeights=None)  # Let ReportLab calculate row heights
    
    # Custom color scheme
    primary_color = colors.Color(61/255, 192/255, 204/255)      # #3DC0CC - Primary teal
    contrast_color = colors.Color(255/255, 202/255, 69/255)     # #FFCA45 - Yellow accent
    alt_row_color = colors.Color(248/255, 252/255, 253/255)     # Very light teal
    border_color = colors.Color(0.6, 0.6, 0.6)                 # Neutral gray for borders
    
    # Create table styles with prominent header and proper vertical alignment
    table_style = [
        # Header row - more prominent/title-like
        ('BACKGROUND', (0, 0), (-1, 0), primary_color),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),          # Horizontal center
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),         # Vertical center for ALL cells
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 15),
        ('TOPPADDING', (0, 0), (-1, 0), 15),
        
        # Data rows with increased padding for better vertical centering
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('GRID', (0, 0), (-1, -1), 0.5, border_color),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, alt_row_color]),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),    # Increased padding
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),   # Increased padding  
        ('TOPPADDING', (0, 1), (-1, -1), 12),    # Increased top padding for data rows
        ('BOTTOMPADDING', (0, 1), (-1, -1), 12), # Increased bottom padding for data rows
        
        # Ensure minimum row height for proper centering
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, alt_row_color]),
    ]
    
    table.setStyle(TableStyle(table_style))
    elements.append(table)
    
    # Enhanced footer function with customer/SO info on all pages
    def add_page_footer(canvas, doc):
        """Add footer with page numbers, generation info, and customer/SO info on all pages"""
        canvas.saveState()
        
        page_width = page_size[0]  # Use the appropriate page width based on orientation
        page_num = canvas.getPageNumber()
        
        # Page number and generation time
        page_text = f"Page {page_num}"
        gen_time = datetime.now().strftime('%m/%d/%Y %I:%M %p')
        gen_text = f"Generated: {gen_time}"
        
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.Color(0.4, 0.4, 0.4))
        
        # Left side - generation time
        canvas.drawString(0.3*inch, 0.3*inch, gen_text)
        # Right side - page number  
        canvas.drawRightString(page_width - 0.3*inch, 0.3*inch, page_text)
        
        # Center - Customer and SO info (on all pages, no labels)
        center_info_parts = []
        
        # Add customer info (always show if customers exist)
        if unique_customers:
            if len(unique_customers) <= 3:
                customer_text = ", ".join(unique_customers)
            else:
                customer_text = f"{', '.join(unique_customers[:2])} + {len(unique_customers)-2} more"
            center_info_parts.append(customer_text)
        
        # Add SO info (always show if sales orders exist)
        if unique_sales_orders:
            if len(unique_sales_orders) <= 5:
                so_text = ", ".join(unique_sales_orders)
            else:
                so_text = f"{', '.join(unique_sales_orders[:3])} + {len(unique_sales_orders)-3} more"
            center_info_parts.append(f"SO: {so_text}")
        
        # Display center info if we have any
        if center_info_parts:
            center_text = " | ".join(center_info_parts)
            # Calculate center position
            text_width = canvas.stringWidth(center_text, 'Helvetica', 8)
            x_position = (page_width - text_width) / 2
            canvas.drawString(x_position, 0.3*inch, center_text)
        
        canvas.restoreState()
    
    # Build PDF with enhanced footer
    doc.build(elements, onFirstPage=add_page_footer, onLaterPages=add_page_footer)
    buffer.seek(0)
    return buffer

# Sidebar for file uploads
st.sidebar.header("📊 Data Sources")

# Sales Order Item History CSV Upload
st.sidebar.subheader("📋 Sales Order Item History")
st.sidebar.markdown("**All Sales Orders with a status of Processing and an order date within the past 30 days**")
so_file = st.sidebar.file_uploader(
    "Upload Sales Order Item History CSV:",
    type=['csv'],
    key="so_upload",
    help="Upload your sales order CSV with processing orders from the last 30 days. The tool will automatically handle metadata lines and column mapping."
)

# Assembly Data CSV Upload  
st.sidebar.subheader("🔧 Assembly Data")
st.sidebar.markdown("**Assemblies from the Last 3 Days**")
assembly_file = st.sidebar.file_uploader(
    "Upload Assembly Data CSV:",
    type=['csv'],
    key="assembly_upload",
    help="Upload your assembly data CSV containing input/output package relationships from the last 3 days."
)

# Product List CSV Upload
st.sidebar.subheader("📦 Product List")
st.sidebar.markdown("**Current product catalog with case quantities**")
product_file = st.sidebar.file_uploader(
    "Upload Product List CSV:",
    type=['csv'],
    key="product_upload",
    help="Upload your product list CSV to calculate cases needed. Uses Product Id to match with sales orders and divides quantity by units per case."
)

# Process button
if st.sidebar.button("🚀 Process Data", type="primary", disabled=not (so_file and assembly_file)):
    with st.spinner("Processing your data..."):
        try:
            # Load the data using our custom function that skips metadata
            so_df = load_csv_with_metadata_skip(so_file)
            assembly_df = load_csv_with_metadata_skip(assembly_file)
            
            # Load product data if available (no metadata skip needed for this one)
            product_df = None
            if product_file:
                try:
                    product_df = pd.read_csv(product_file)
                    st.session_state.product_data = product_df
                    st.info(f"Product List: {len(product_df):,} products loaded")
                except Exception as e:
                    st.warning(f"Could not load Product List: {str(e)}. Continuing without case quantities.")
            
            if so_df is None or assembly_df is None:
                st.error("❌ Failed to load required CSV files. Please check your file formats.")
                st.stop()
            
            st.session_state.so_data = so_df
            st.session_state.assembly_data = assembly_df
            
            file_info = f"Sales Orders: {len(so_df):,} rows | Assembly Data: {len(assembly_df):,} rows"
            if product_df is not None:
                file_info += f" | Products: {len(product_df):,} rows"
            
            st.success(f"✅ Files loaded successfully!")
            st.info(file_info)
            
            # Process the data
            processed_df = process_data(so_df, assembly_df, product_df)
            
            if processed_df is not None:
                st.session_state.processed_data = processed_df
                st.success(f"✅ Successfully processed {len(processed_df):,} records")
            else:
                st.error("❌ Failed to process data. Please check your CSV file structure.")
                
        except Exception as e:
            st.error(f"❌ Error processing files: {str(e)}")

# Main content area
if st.session_state.processed_data is not None:
    processed_df = st.session_state.processed_data
    
    # Create tabs for better organization
    tab1, tab2 = st.tabs(["🎯 Pick List Generator", "📊 Data Overview"])
    
    with tab1:
        st.header("🎯 Create Custom Pick List")
        
        # Filter section
        col1, col2, col3 = st.columns([2, 2, 2])
        
        with col1:
            customers = sorted(processed_df['Customer'].unique().tolist())
            selected_customers = st.multiselect("Select Customers", customers)
            
        with col2:
            if selected_customers:
                filtered_orders = processed_df[processed_df['Customer'].isin(selected_customers)]['Order_Number'].unique()
            else:
                filtered_orders = processed_df['Order_Number'].unique()
            orders = sorted(filtered_orders.tolist())
            selected_orders = st.multiselect("Select Sales Orders", orders)
            
        with col3:
            if selected_customers:
                filtered_categories = processed_df[processed_df['Customer'].isin(selected_customers)]['Category'].unique()
            elif selected_orders:
                filtered_categories = processed_df[processed_df['Order_Number'].isin(selected_orders)]['Category'].unique()
            else:
                filtered_categories = processed_df['Category'].unique()
            categories = sorted(filtered_categories.tolist())
            selected_categories = st.multiselect("Select Categories", categories)
        
        # PDF Options and Generate Button
        col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
        
        with col1:
            hide_customer = st.checkbox("Hide Customer Column", help="Remove Customer column from PDF report")
        
        with col2:
            hide_sales_order = st.checkbox("Hide SO Column", help="Remove Sales Order column from PDF report")
        
        with col3:
            portrait_mode = st.checkbox("Portrait Mode", help="Generate PDF in portrait orientation instead of landscape")
        
        with col4:
            generate_pdf_btn = st.button("📑 Generate PDF", type="primary")
        
        # Apply filters
        filtered_df = processed_df.copy()
        
        applied_filters = {}
        
        if selected_customers:
            filtered_df = filtered_df[filtered_df['Customer'].isin(selected_customers)]
            applied_filters['Customers'] = selected_customers
            
        if selected_orders:
            filtered_df = filtered_df[filtered_df['Order_Number'].isin(selected_orders)]
            applied_filters['Sales Orders'] = selected_orders
            
        if selected_categories:
            filtered_df = filtered_df[filtered_df['Category'].isin(selected_categories)]
            applied_filters['Categories'] = selected_categories
        
        # Show filtered results
        st.subheader(f"📋 Pick List Results ({len(filtered_df):,} records)")
        st.dataframe(filtered_df, use_container_width=True)
        
        # Download section
        col1, col2 = st.columns(2)
        
        with col1:
            # CSV download
            csv = filtered_df.to_csv(index=False)
            st.download_button(
                label="📄 Download CSV",
                data=csv,
                file_name=f"pick_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        
        with col2:
            # PDF download (triggered by the button above)
            if generate_pdf_btn:
                with st.spinner("Generating PDF report..."):
                    pdf_buffer = generate_pdf(filtered_df, applied_filters, hide_customer, hide_sales_order, portrait_mode)
                    
                # Immediately trigger download
                st.download_button(
                    label="📑 Download PDF Report",
                    data=pdf_buffer,
                    file_name=f"pick_list_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf",
                    mime="application/pdf",
                    use_container_width=True,
                    key="pdf_download"
                )
                st.success("✅ PDF report generated successfully!")
            else:
                # Show placeholder when PDF not generated
                st.button("📑 Download PDF Report", disabled=True, help="Click 'Generate PDF' button above first", use_container_width=True)
    
    with tab2:
        st.header("📊 Data Overview")
        
        # Summary metrics
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("🛒 Total Sales Orders", len(processed_df['Order_Number'].unique()))
        with col2:
            st.metric("👥 Unique Customers", len(processed_df['Customer'].unique()))
        with col3:
            st.metric("📦 Total Items", len(processed_df))
        with col4:
            st.metric("🏷️ Categories", len(processed_df['Category'].unique()))
        with col5:
            # Show cases calculation coverage if product data was loaded
            if 'Cases' in processed_df.columns:
                cases_coverage = processed_df['Cases'].notna().sum()
                coverage_pct = (cases_coverage / len(processed_df) * 100) if len(processed_df) > 0 else 0
                st.metric("📦 Cases Coverage", f"{coverage_pct:.0f}%")
            else:
                st.metric("📦 Cases Coverage", "0%")
        
        # Show breakdown by category
        st.subheader("📈 Category Breakdown")
        category_counts = processed_df['Category'].value_counts()
        st.bar_chart(category_counts)
        
        # Show breakdown by customer
        st.subheader("👥 Customer Breakdown")
        customer_counts = processed_df['Customer'].value_counts().head(10)
        st.bar_chart(customer_counts)
        
        # Show case analysis if available
        if 'Cases' in processed_df.columns and processed_df['Cases'].notna().sum() > 0:
            st.subheader("📦 Cases Analysis")
            col1, col2 = st.columns(2)
            
            with col1:
                # Items with calculated cases
                items_with_cases = processed_df[processed_df['Cases'].notna() & (processed_df['Cases'] != "")]
                st.write(f"**Items with Cases Calculated:** {len(items_with_cases):,} of {len(processed_df):,}")
                
                if len(items_with_cases) > 0:
                    # Convert to numeric for analysis
                    cases_numeric = pd.to_numeric(items_with_cases['Cases'], errors='coerce')
                    cases_numeric = cases_numeric.dropna()
                    
                    if len(cases_numeric) > 0:
                        st.write(f"**Average Cases per Line:** {cases_numeric.mean():.2f}")
                        st.write(f"**Total Cases:** {cases_numeric.sum():.2f}")
                        st.write(f"**Largest Line:** {cases_numeric.max():.2f} cases")
            
            with col2:
                # Cases distribution
                if len(items_with_cases) > 0:
                    # Group cases into ranges for better visualization
                    cases_numeric = pd.to_numeric(items_with_cases['Cases'], errors='coerce').dropna()
                    if len(cases_numeric) > 0:
                        # Create ranges
                        cases_ranges = pd.cut(cases_numeric, bins=[0, 0.5, 1, 2, 5, 10, float('inf')], 
                                            labels=['< 0.5', '0.5-1', '1-2', '2-5', '5-10', '10+'])
                        cases_range_counts = cases_ranges.value_counts().sort_index()
                        st.write("**Cases Distribution:**")
                        st.bar_chart(cases_range_counts)
        
        # Show raw data with search
        st.subheader("🔍 Full Dataset")
        st.dataframe(processed_df, use_container_width=True)

else:
    # Welcome screen when no data is loaded
    if not so_file and not assembly_file:
        st.info("👈 Upload the required CSV files in the sidebar to get started")
        
        # Show helpful information
        with st.expander("ℹ️ How it Works", expanded=True):
            st.markdown("""
            **📋 Upload** → **🔄 Process** → **🎯 Filter** → **📥 Download**
            
            This tool processes your sales order, assembly, and product data to create custom pick lists with input package tracking and calculated case requirements.
            
            **Key Features:**
            - 🔗 Links Package Labels to Assembly Numbers
            - 🔍 Finds Input Package Numbers for tracking
            - 📦 Calculates cases needed (Quantity ÷ Units Per Case)
            - 📑 Generates formatted PDF reports with pick checkboxes
            - 🎯 Filter by customer, order, or category
            - 📊 Data overview and analytics
            """)
        
        with st.expander("📁 CSV File Requirements"):
            st.markdown("""
            **Sales Order Item History CSV:** *(Required)*
            - Status: Processing orders only
            - Date Range: Past 30 days
            - Required columns: Customer, Order Number, Category, Product, Product Id, Package Batch Number, Package Label, Quantity
            - Note: "Order Number" column will display as "Sales Order" in reports
            
            **Assembly Data CSV:** *(Required)*
            - Date Range: Last 3 days
            - Required columns: Input/Output, Package Number, Assembly Number
            - Both input and output records needed for proper linking
            
            **Product List CSV:** *(Optional)*
            - Current product catalog
            - Required columns: ID, Units Per Case
            - Used to calculate cases needed by dividing quantity by units per case
            
            *The tool automatically handles metadata lines and column mapping for Sales Order and Assembly files.*
            """)
    
    elif so_file and assembly_file:
        st.info("👈 Click the 'Process Data' button in the sidebar to analyze your files")
        if product_file:
            st.info("📦 Product List detected - cases will be calculated in the report")
        else:
            st.info("💡 Tip: Upload a Product List CSV to include calculated cases in your pick list")
    
    else:
        missing_files = []
        if not so_file:
            missing_files.append("Sales Order Item History")
        if not assembly_file:
            missing_files.append("Assembly Data")
        
        st.warning(f"📁 Please upload the {' and '.join(missing_files)} CSV file(s) to continue")
        if product_file and not (so_file and assembly_file):
            st.info("📦 Product List uploaded - add the other required files to process data")